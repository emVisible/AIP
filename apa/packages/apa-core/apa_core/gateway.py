"""apa-core: APA-Gateway（设计文档 §8）。

所有 AIP 消息必须经过 Gateway（唯一守卫线）。职责：
  · 信封校验 / 版本 / 来源绑定（I9）/ Session 有效性 / 序列（S1–S5）
  · 事件命名空间 + CoD-1（4KB 上限）校验
  · action 前置校验链（§8.2）：Registry → Schema → 权限 → Session 状态
    → 凭据扫描（C4/I10）→ 策略（§9.2 风险分级）→ 审计 → RetryScheduler → 转发
  · 重试调度（§8.3）：仅 idempotency=required，复用同一 action.id
  · Session 状态机（§10.1）：human.task → SUSPENDED / 完成 → 恢复
  · 审计事件流（append-only）
"""
from __future__ import annotations

import json
import re
from collections import deque
from typing import Callable, Dict, List, Optional

from aip import (
    ActionStore,
    Clock,
    Message,
    Receiver,
    Sequencer,
    Session,
    make_error,
    make_event,
    now_ms,
    make_result,
    validate_message,
)

from .audit import AuditService
from .human_loop import HumanTaskManager
from .policy import PolicyConfig, PolicyDecision
from .registry import ActionRegistry
from .sequence_compat import RecoverableReceiver
from .session import SessionStateMachine

CREDENTIAL_PATTERNS = [
    re.compile(r"Bearer [A-Za-z0-9._~+/=-]+"),
    re.compile(r"password[\"']?\s*[:=]", re.IGNORECASE),
    re.compile(r"Authorization[\"']?\s*[:=]", re.IGNORECASE),
    re.compile(r"api_key", re.IGNORECASE),
    re.compile(r"(?:secret|token|apikey)[\"']?\s*[:=]", re.IGNORECASE),
]

# APA-Profile 事件域（§4.1）
ALLOWED_EVENT_DOMAINS = {
    "browser", "desktop", "document", "erp", "crm", "form",
    "bot", "human", "page", "order", "session", "context",
}
EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,}$")
# 命令式事件名禁止（§4.1 禁止项）
FORBIDDEN_EVENT_SEGMENTS = {"please", "do", "make", "execute", "click", "go"}

MAX_EVENT_DATA_BYTES = 4096  # CoD-1


class GatewayValidationError(Exception):
    pass


class RetryScheduler:
    """§8.3：超时跟踪所有带 timeout 的动作；只重试 idempotency=required，
    重试复用同一 action.id（Executor 侧 dedup 返回存储结果）。"""

    def __init__(self, gateway: "APAGateway", clock: Optional[Clock] = None) -> None:
        self.gateway = gateway
        self.clock = clock
        self._timers: Dict[str, int] = {}       # action_id -> expiry_ms
        self._retries_left: Dict[str, int] = {} # action_id -> 剩余重试次数
        self.retry_events = 0

    def now(self) -> int:
        return self.clock.now_ms() if self.clock else now_ms()

    def schedule(self, action_msg: Message, entry) -> None:
        if entry is None or not entry.timeout_ms:
            return
        self._timers[action_msg.id] = self.now() + entry.timeout_ms
        self._retries_left[action_msg.id] = (
            entry.retries if entry.idempotency == "required" else 0)

    def tick(self) -> None:
        """推进超时。Gateway 在时钟前移后调用（或真实定时器）。"""
        now = self.now()
        for action_id in list(self._timers):
            if now < self._timers[action_id]:
                continue
            # 已有终态结果 → 撤销定时器
            if self.gateway.session.actions.outcome(action_id) is not None:
                self.cancel(action_id)
                continue
            left = self._retries_left.get(action_id, 0)
            if left > 0:
                self.retry_events += 1
                self._retries_left[action_id] = left - 1
                self.gateway._redeliver(action_id)
                msg = self.gateway.pending.get(action_id)
                entry = self.gateway.registry.get(
                    msg.payload.get("name", "")) if msg else None
                self._timers[action_id] = now + (entry.timeout_ms if entry else 0)
            else:
                self.gateway.session.actions.mark(action_id, "timeout")
                self.gateway.pending.pop(action_id, None)
                self.cancel(action_id)

    def cancel(self, action_id: str) -> None:
        self._timers.pop(action_id, None)
        self._retries_left.pop(action_id, None)


class APAGateway:
    """每个活跃 Session 持有一个 Gateway 实例（§8.2）。"""

    def __init__(
        self,
        session_id: str,
        *,
        registry: Optional[ActionRegistry] = None,
        policy: Optional[PolicyConfig] = None,
        # side -> 期望来源；executor 侧可为 list（§10.3 多 Bot 并发）
        identities: Optional[Dict[str, str | List[str]]] = None,
        audit: Optional[AuditService] = None,
        clock: Optional[Clock] = None,
        process_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        journal=None,
        session_ttl_ms: Optional[int] = None,
        rate_limit_per_minute: Optional[int] = None,
    ) -> None:
        self.session_id = session_id
        self.session = Session(session_id)
        self.session.receiver = RecoverableReceiver()
        self.session.actions = ActionStore()
        self.registry = registry or ActionRegistry()
        self.policy = policy or PolicyConfig()
        self.identities = identities or {}
        self.audit = audit or AuditService()
        self.clock = clock
        self.journal = journal
        self.human = HumanTaskManager()
        self.sm = SessionStateMachine(
            session_id, process_id=process_id, tenant_id=tenant_id, clock=clock,
            on_transition=[self._on_transition] if journal else [])

        self.handlers: Dict[str, Callable[[dict], None]] = {}
        self.outbound: Dict[str, List[dict]] = {"executor": [], "agent": []}
        self.connected: Dict[str, bool] = {"executor": True, "agent": True}
        self.pending: Dict[str, Message] = {}
        self.forwarded_ids: List[str] = []
        self.executions = 0
        self.rejections: List[tuple] = []
        self.duplicates = 0
        self.retry_scheduler = RetryScheduler(self, clock)
        self.emitted: List[Message] = []
        self.human_task_outcomes: Dict[str, str] = {}
        # expect 跟踪（AIP §4.2 / Registry.expect）：action → 期望后续事件
        self.pending_expects: Dict[str, str] = {}   # action_id -> event name
        self.satisfied_expects: int = 0
        # Session TTL（K2）：无活动超过 ttl 即过期
        self.session_ttl_ms = session_ttl_ms
        self._last_activity_ms: Optional[int] = None
        # Gateway 自有消息的流序号（对端 Receiver 需要连续 seq 才会接受）
        self._gw_seq = Sequencer()
        # 速率限制（§12 安全：按来源的滑动窗口，60s）
        self.rate_limit_per_minute = rate_limit_per_minute
        self._action_times: Dict[str, deque] = {}
        # 动作耗时统计起点（Analytics）
        self._action_started_ms: Dict[str, int] = {}

    # --- journal（Session 持久化，§10.1） ---------------------------------------
    def _on_transition(self, to: str, frm: str) -> None:
        self._journal("state", to=to)

    def _journal(self, kind: str, **fields) -> None:
        if self.journal is not None:
            self.journal.record(kind, session=self.session_id,
                                tenant=self.sm.record.tenant_id, **fields)

    # --- wiring ---------------------------------------------------------------
    def set_handler(self, side: str, handler: Callable[[dict], None]) -> None:
        self.handlers[side] = handler

    def deliver(self, side: str, raw: dict) -> None:
        """side 上的 peer 发送消息。校验后路由。

        路由规则：
          · 转发的原始消息 → 对端 peer
          · Gateway 生成的结果（rejected/timeout 等）→ 回发给发送方
        """
        outbound = self.receive(side, raw)
        for msg in outbound:
            target_side = self._route(msg, side)
            if not self.connected.get(target_side, False):
                continue
            target = self.handlers.get(target_side)
            if target is not None:
                target(msg.to_dict())

    def _route(self, msg: Message, from_side: str) -> str:
        if msg.type in ("result", "error") and msg.source == "gateway":
            return from_side  # Gateway 生成的拒绝/超时/协议错误 → 发送方
        return self._other(from_side)

    @staticmethod
    def _other(side: str) -> str:
        return "agent" if side == "executor" else "executor"

    # --- core: receive ----------------------------------------------------------
    def _identity_ok(self, side: str, source: str) -> bool:
        expected = self.identities.get(side)
        if expected is None:
            return False
        if isinstance(expected, (list, tuple, set)):
            return source in expected
        return source == expected

    def executor_sources(self) -> List[str]:
        """当前会话全部 executor 来源（§10.3 多 Bot）。"""
        expected = self.identities.get("executor", [])
        if isinstance(expected, (list, tuple, set)):
            return list(expected)
        return [expected] if expected else []

    def receive(self, side: str, raw: dict) -> List[Message]:
        msg = Message.from_dict(raw)
        self.emitted.append(msg)
        self.sm.stats_bump(msg.type + "s" if msg.type != "event" else "events")

        # 1. 信封校验
        errors = validate_message(msg)
        if errors:
            return self._fail(side, msg, "INVALID_MESSAGE", "; ".join(errors))

        # 2. 版本
        if msg.v != 1:
            return self._fail(side, msg, "UNSUPPORTED_VERSION")

        # 3. 身份绑定（I9，支持多 Bot 成员校验）
        if not self._identity_ok(side, msg.source):
            self.rejections.append(("I9", side, msg.source))
            return self._fail(side, msg, "UNAUTHORIZED")

        # 4. Session 有效性（K2 + TTL 空闲过期）
        if not self.session.is_active() or self._ttl_expired():
            return self._fail(side, msg, "SESSION_EXPIRED")
        self._touch_activity()

        # 5. 序列检查（S1–S5）
        cls = self.session.receiver.classify(msg)
        if cls == "duplicate":
            self.duplicates += 1
            return self._finish(side, self._on_duplicate(side, msg))
        if cls != "accept":
            return self._fail(side, msg, "SEQ_OUT_OF_ORDER")
        self.session.receiver.apply(msg)
        self.sm.record.cursors[msg.source] = msg.seq
        self._journal("cursor", source=msg.source, seq=msg.seq)

        # 6. 类型分发
        if msg.type == "event":
            return self._finish(side, self._on_event(side, msg))
        if msg.type == "action":
            return self._finish(side, self._on_action(side, msg))
        if msg.type == "result":
            return self._finish(side, self._on_result(side, msg))
        return self._fail(side, msg, "INVALID_MESSAGE", "unknown type")

    def _now(self) -> int:
        # 无注入时钟时回退真实墙钟（独立部署的时间性语义依赖此路径）
        return self.clock.now_ms() if self.clock else now_ms()

    def _touch_activity(self) -> None:
        self._last_activity_ms = self._now()

    def _ttl_expired(self) -> bool:
        if self.session_ttl_ms is None or self._last_activity_ms is None:
            return False  # 首条消息前不判 TTL
        return self._now() - self._last_activity_ms > self.session_ttl_ms

    def _finish(self, side: str, outbound: List[Message]) -> List[Message]:
        for m in outbound:
            self._assign_seq(m)
            self.outbound[self._other(side)].append(m.to_dict())
        return outbound

    def _assign_seq(self, m: Message) -> None:
        """Gateway 自有消息（source=gateway）必须占用 (session, gateway) 流的
        连续 seq，否则对端 Receiver 会判 stale 丢弃（S1–S5）。"""
        if m.source == "gateway" and not m.seq:
            m.seq = self._gw_seq.next(self.session_id, "gateway")

    def _fail(self, side: str, msg: Message, code: str, detail: str = "") -> List[Message]:
        self.audit.log_error(self.session_id, code, detail or msg.id)
        return self._finish(side, [make_error(
            self.session_id, "gateway", code, in_reply_to=msg.id, message=detail or None)])

    # --- events ----------------------------------------------------------------
    def _on_event(self, side: str, msg: Message) -> List[Message]:
        name = msg.payload.get("name", "")
        data = msg.payload.get("data") or {}

        # 事件命名空间校验（§4.1）
        if not self._validate_event_name(name):
            self.rejections.append(("EVENT_NS", side, name))
            return self._fail(side, msg, "INVALID_MESSAGE", f"bad event name {name!r}")

        # CoD-1：事件 data ≤ 4KB
        size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        self.audit.log_event(self.session_id, msg.source, name, size, ts=msg.ts)
        if size > MAX_EVENT_DATA_BYTES:
            self.rejections.append(("COD1", side, size))
            return self._fail(side, msg, "INVALID_MESSAGE",
                              f"event data exceeds {MAX_EVENT_DATA_BYTES} bytes (CoD-1)")

        # 业务域事件只由 Executor 发出（§4.1 禁止项）；agent 侧事件拒绝
        if side != "executor" and not name.startswith("bot."):
            self.rejections.append(("EVENT_SRC", side, name))
            return self._fail(side, msg, "INVALID_MESSAGE",
                              f"business event {name!r} must come from executor")

        # 人工任务完成 → 恢复 Session（§4.3）
        if name == "human.task.completed":
            task_id = (data or {}).get("task_id")
            if task_id:
                self.sm.resume_after_human(task_id)
                self.human_task_outcomes[task_id] = str((data or {}).get("outcome"))

        # expect 满足检查（AIP §4.2）
        if name in self.pending_expects.values():
            for action_id, expected in list(self.pending_expects.items()):
                if expected == name:
                    del self.pending_expects[action_id]
                    self.satisfied_expects += 1

        return [msg]  # 转发给 Decision Engine

    def _validate_event_name(self, name: str) -> bool:
        if not isinstance(name, str) or not EVENT_NAME_RE.match(name):
            return False
        parts = name.split(".")
        if any(p in FORBIDDEN_EVENT_SEGMENTS for p in parts):
            return False
        return parts[0] in ALLOWED_EVENT_DOMAINS

    # --- actions ----------------------------------------------------------------
    def _on_action(self, side: str, msg: Message) -> List[Message]:
        name = msg.payload.get("name", "")
        params = msg.payload.get("params", {})
        self.session.actions.register(msg.id, name, msg.source)

        # 幂等：已结算的 action → 返回存储结果（A3/A4）
        outcome = self.session.actions.outcome(msg.id)
        if outcome is not None:
            status, result_id = outcome
            self.duplicates += 1
            return [make_result(
                self.session_id, "gateway", status, msg.id,
                duplicate=True, original_result_id=result_id)]

        # ⓪ 速率限制：按来源滑动窗口（60s）
        if self.rate_limit_per_minute is not None:
            rl_now = self._now()
            window = self._action_times.setdefault(msg.source, deque())
            while window and rl_now - window[0] > 60_000:
                window.popleft()
            if len(window) >= self.rate_limit_per_minute:
                self.rejections.append(("RATE", msg.id, msg.source))
                return [make_result(self.session_id, "gateway", "rejected",
                                    msg.id, code="rate_limited")]
            window.append(rl_now)

        # ① Registry 查找
        entry = self.registry.get(name)
        if entry is None or entry.deprecated:
            self.rejections.append(("REGISTRY", msg.id, name))
            return [make_result(self.session_id, "gateway", "rejected",
                                msg.id, code="action_not_registered")]

        # ⓪ C3：idempotency/risk 只能来自 Registry，禁止消息携带
        contraband = {"idempotency", "risk"} & set(msg.payload.keys())
        if contraband:
            self.rejections.append(("C3", msg.id, sorted(contraband)))
            return [make_result(self.session_id, "gateway", "rejected",
                                msg.id, code="invalid_action",
                                message=f"C3: {sorted(contraband)} must come from Action Registry")]

        # ② Params Schema 校验
        schema_errors = entry.validate_params(params)
        if schema_errors:
            self.rejections.append(("SCHEMA", msg.id, name))
            return [make_result(self.session_id, "gateway", "rejected",
                                msg.id, code="invalid_params", message="; ".join(schema_errors))]

        # ③ 权限（allowed_principals）
        if entry.allowed_principals and msg.source not in entry.allowed_principals:
            self.rejections.append(("PERM", msg.id, msg.source))
            return [make_result(self.session_id, "gateway", "rejected",
                                msg.id, code="permission_denied")]

        # ④ Session 状态匹配（§10.1）
        #    终态：拒绝一切新动作；SUSPENDED：禁止 L2+ 业务动作执行
        if self.sm.record.is_terminal() or \
                (self.sm.state == "SUSPENDED" and entry.risk in ("L2", "L3", "L4")):
            self.rejections.append(("SESS", msg.id, self.sm.state))
            return [make_result(self.session_id, "gateway", "rejected",
                                msg.id, code="session_state_mismatch")]

        # ⑤ 凭据扫描（C4/I10）
        if self._scan(msg):
            self.rejections.append(("C4", msg.id, name))
            self.audit.log_error(self.session_id, "credential_in_payload", name)
            return [make_result(self.session_id, "gateway", "rejected",
                                msg.id, code="credential_in_payload")]

        # 会话控制：session.complete 由 Gateway 处理，不转发 Executor
        if name == "session.complete":
            outcome = params.get("outcome", "success")
            self.sm.complete(outcome)
            self._journal("outcome", outcome=outcome,
                          reason=params.get("summary", ""))
            self._audit_action(msg, entry, verdict="permitted", rule="session_control")
            return [make_result(self.session_id, "gateway", "ok", msg.id,
                                data={"outcome": outcome})]

        # ui.confirm（M5）：HITL 轻量形态——确认型任务，resolve 返回 ok
        if name == "ui.confirm":
            task_id = self.human.create(
                action_id=msg.id,
                task_type="confirm",
                assignee_role=params.get("assignee_role", "rpa_operator"),
                context_ref=params.get("context_ref", ""),
                priority=params.get("priority", "normal"),
            )
            self.sm.suspend_for_human(task_id)
            self._journal("task", task_id=task_id, status="open",
                          task_type="confirm",
                          title=str(params.get("title", ""))[:120],
                          message=str(params.get("message", ""))[:500])
            return [make_result(self.session_id, "gateway", "ok",
                                 msg.id, data={"task_id": task_id})]

        # 人工干预：human.task.create 由 Gateway 处理（§4.3）
        # 创建任务 + Session SUSPENDED；人工完成后经 resolve_human_task 恢复
        if name == "human.task.create":
            task_id = self.human.create(
                action_id=msg.id, task_type=params.get("task_type", "exception"),
                assignee_role=params.get("assignee_role", "rpa_operator"),
                context_ref=params.get("context_ref", ""),
                priority=params.get("priority", "normal"),
            )
            self.sm.suspend_for_human(task_id)
            self._audit_action(msg, entry, verdict="permitted", rule="human_task")
            self._journal("task", task_id=task_id, status="open",
                          task_type=params.get("task_type", "exception"))
            return [make_result(self.session_id, "gateway", "ok", msg.id,
                                data={"task_id": task_id})]

        # ⑥ 策略评估（§9.2 风险分级）
        policy_ctx = self._policy_context(params)
        decision, rule = self.policy.evaluate(name, entry, policy_ctx,
                                              source=msg.source)
        if decision == PolicyDecision.REJECT:
            self.rejections.append(("POLICY", msg.id, rule))
            return [make_result(self.session_id, "gateway", "rejected",
                                msg.id, code="policy_violation", message=rule)]

        if decision == PolicyDecision.REQUIRE_HUMAN:
            return self._create_human_task_and_suspend(msg, entry, rule)

        # ⑦ 审计 + 调度 + 转发
        self._audit_action(msg, entry, verdict="permitted", rule=rule)
        self.retry_scheduler.schedule(msg, entry)
        if entry.expect:
            self.pending_expects[msg.id] = entry.expect  # AIP §4.2
        self._action_started_ms[msg.id] = now_ms()
        self._journal("action", action_id=msg.id, name=name,
                      source=msg.source, risk=entry.risk, verdict="permitted")
        self._forward(msg)
        return [msg]

    def _policy_context(self, params: dict) -> dict:
        """从 params 提取策略条件（金额等）。为安全起见只取标量字段。"""
        ctx: dict = {}
        for k, v in params.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                ctx[k] = v
        return ctx

    def _audit_action(self, msg: Message, entry, verdict: str, rule: str) -> None:
        params = msg.payload.get("params", {})
        # audit_fields 明文记录；audit_mask_fields 记录但掩码（§9.3）
        audit_params = {p: params[p] for p in entry.audit_fields if p in params}
        for f in entry.audit_mask_fields:
            if f in params:
                audit_params[f] = "***"
        self.audit.log_action(
            audit_id=msg.id,
            session_id=self.session_id,
            process_id=self.sm.record.process_id,
            tenant_id=self.sm.record.tenant_id,
            action_id=msg.id,
            action_name=msg.payload.get("name", ""),
            source=msg.source,
            executor=self._route_executor(entry),
            in_reply_to_event=msg.in_reply_to,
            verdict=verdict,
            risk_level=entry.risk,
            policy_rules_applied=[rule],
            credential_scan="clean",
            params_audit=audit_params,
            mask_fields=entry.audit_mask_fields,
            event_ts=msg.ts,
        )

    def _route_executor(self, entry) -> str:
        sources = self.executor_sources()
        return sources[0] if sources else "executor"

    def _create_human_task_and_suspend(self, msg: Message, entry, rule: str) -> List[Message]:
        """L3/L4 或策略要求人工 → 创建 human.task + 挂起 Session（§4.3）。"""
        task_id = f"ht_{msg.id}"
        self.sm.suspend_for_human(task_id)
        self._audit_action(msg, entry, verdict="require_human", rule=rule)
        self.audit.log_error(self.session_id, "requires_human_approval",
                             f"{msg.payload.get('name')} -> {task_id}")
        # 通知 Executor 侧（human 域）创建任务。POC 简化：直接回 rejected 由
        # 决策引擎走 human.task.create 流程。见 §8.2 注释。
        return [make_result(
            self.session_id, "gateway", "rejected", msg.id,
            code="requires_human_approval", message=rule)]

    # --- results ---------------------------------------------------------------
    def _on_result(self, side: str, msg: Message) -> List[Message]:
        status = msg.payload.get("status", "")
        action_id = msg.in_reply_to or ""
        result = self.session.actions.mark(action_id, status, msg.id)
        if result == "after_terminal":
            self.rejections.append(("I6", action_id, status))
            return []
        if result == "unknown_action":
            return self._fail(side, msg, "INVALID_MESSAGE", "result for unknown action")
        if status in ("ok", "failed", "timeout", "rejected"):
            self.retry_scheduler.cancel(action_id)
            started = self._action_started_ms.pop(action_id, None)
            duration = (now_ms() - started) if started is not None else None
            action_name = ""
            act_meta = self.session.actions.actions.get(action_id) or {}
            action_name = act_meta.get("name", "")
            self._journal("action_result", action_id=action_id, status=status,
                          name=action_name,
                          **({"duration_ms": duration} if duration is not None else {}))
        self.sm.stats_bump("results")

        # 会话控制 action 的结果 → 驱动状态机
        action = self.session.actions.actions.get(action_id)
        if action:
            name = action.get("name", "")
            if name == "session.complete" and status in ("ok", "failed"):
                outcome = msg.payload.get("data", {}).get("outcome", "success") if status == "ok" else "failure"
                self.sm.complete(outcome)
        return [msg]

    # --- duplicates ------------------------------------------------------------
    def _on_duplicate(self, side: str, msg: Message) -> List[Message]:
        if msg.type == "action":
            outcome = self.session.actions.outcome(msg.id)
            if outcome is not None:
                status, result_id = outcome
                return [make_result(
                    self.session_id, "gateway", status, msg.id,
                    duplicate=True, original_result_id=result_id)]
        return []

    # --- delivery --------------------------------------------------------------
    def _forward(self, msg: Message) -> None:
        self.executions += 1
        self.forwarded_ids.append(msg.id)
        self.pending[msg.id] = msg
        # 不在协议中携带 idempotency/risk（C3）——仅保留原始 action

    def _redeliver(self, action_id: str) -> None:
        msg = self.pending.get(action_id)
        if msg is None:
            return
        self.executions += 1
        self.forwarded_ids.append(action_id)
        raw = msg.to_dict()
        self.outbound["executor"].append(raw)
        if self.connected.get("executor") and self.handlers.get("executor"):
            self.handlers["executor"](raw)

    # --- credential scan --------------------------------------------------------
    def _scan(self, msg: Message) -> bool:
        try:
            blob = json.dumps(msg.payload, ensure_ascii=False)
        except (TypeError, ValueError):
            return True
        return any(p.search(blob) for p in CREDENTIAL_PATTERNS)

    # --- resume / heartbeat ------------------------------------------------------
    def disconnect(self, side: str) -> None:
        self.connected[side] = False
        if side == "executor":
            self.sm.executor_lost(side)
            if self.sm.state == "RUNNING":
                self.sm.transition("RECOVERING")

    def reconnect(self, side: str, cursors: Optional[dict] = None) -> None:
        self.connected[side] = True
        if side == "executor":
            self.sm.executor_reconnected(side, 0)
            if self.sm.state == "RECOVERING":
                self.sm.transition("RUNNING")
        self.resume(side, cursors)

    def resume(self, side: str, cursors: Optional[dict] = None) -> None:
        cursors = cursors or {}
        target = self.handlers.get(side)
        if target is None:
            return
        for raw in list(self.outbound[side]):
            cur = cursors.get(raw.get("source"))
            if cur is None or raw.get("seq", 0) > cur:
                target(raw)

    def hello(self) -> dict:
        return {"session": self.session_id, "cursors": self.session.cursors(),
                "state": self.sm.state}

    def tick(self) -> None:
        self.retry_scheduler.tick()

    # --- 紧急熔断（§12.4：Session 强制终止，in-flight 标记 timeout） --------------
    def abort(self, reason: str = "manual_abort") -> bool:
        """强制终止会话：未决 action 全部标记 timeout，Session → CANCELLED。

        与人工任务无关的挂起一并解除；审计与日志各留一条。
        """
        if self.sm.record.is_terminal():
            return False
        for action_id in list(self.pending.keys()):
            self.session.actions.mark(action_id, "timeout")
            self.retry_scheduler.cancel(action_id)
        self.pending.clear()
        for task_id in list(self.sm.record.human_tasks):
            self.sm.resume_after_human(task_id)
            if self.human.get(task_id):
                self.human.resolve(task_id, outcome="aborted", actor="gateway")
        self.sm.cancel()
        self._journal("outcome", outcome="cancelled", reason=reason)
        self.audit.log_error(self.session_id, "SESSION_ABORTED", reason)
        return True

    def unsatisfied_expects(self) -> Dict[str, str]:
        """尚未收到期望事件的 action（§4.2 expect；POC 不做超时强判）。"""
        return dict(self.pending_expects)

    # --- 人工任务闭环（§4.3） -----------------------------------------------------
    def resolve_human_task(
        self, task_id: str, outcome: str = "retry",
        actor: str = "operator", comment: str = "",
    ) -> bool:
        """人工完成任务 → 注入 human.task.completed 事件 → Session 恢复。

        以 executor principal 在协议内注入（内部通道，seq 取该流下一序号）。
        """
        if not self.human.resolve(task_id, outcome=outcome, actor=actor):
            return False
        source = self.identities.get("executor", "")
        if not source:
            return False
        seq = self.session.receiver.cursor(self.session_id, source) + 1
        ev = make_event(self.session_id, source, "human.task.completed",
                        data={"task_id": task_id, "outcome": outcome,
                              "actor": actor, "comment": comment},
                        seq=seq, id=f"evt_human_{task_id}")
        self.deliver("executor", ev.to_dict())
        self._journal("task", task_id=task_id, status="resolved", outcome=outcome)
        return True

    # --- introspection ----------------------------------------------------------
    def applied_counts(self) -> dict:
        receiver = self.session.receiver
        return {
            source: receiver.applied_count(self.session_id, source)
            for source in {entry[1] for entry in receiver.history}
        }

    def summary(self) -> dict:
        s = self.sm.summary()
        s.update({
            "executions": self.executions,
            "duplicates": self.duplicates,
            "rejections": len(self.rejections),
            "retry_events": self.retry_scheduler.retry_events,
            "audit_records": len(self.audit.read_all()),
            "expects_pending": len(self.pending_expects),
            "expects_satisfied": self.satisfied_expects,
        })
        return s