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
from typing import Callable, Dict, List, Optional

from aip import (
    ActionStore,
    Clock,
    Message,
    Receiver,
    Session,
    make_error,
    make_result,
    validate_message,
)

from .audit import AuditService
from .policy import PolicyConfig, PolicyDecision
from .registry import ActionRegistry
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
        return self.clock.now_ms() if self.clock else 0

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
        identities: Optional[Dict[str, str]] = None,  # side -> expected source
        audit: Optional[AuditService] = None,
        clock: Optional[Clock] = None,
        process_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        self.session_id = session_id
        self.session = Session(session_id)
        self.session.receiver = Receiver()
        self.session.actions = ActionStore()
        self.registry = registry or ActionRegistry()
        self.policy = policy or PolicyConfig()
        self.identities = identities or {}
        self.audit = audit or AuditService()
        self.clock = clock
        self.sm = SessionStateMachine(
            session_id, process_id=process_id, tenant_id=tenant_id, clock=clock)

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

        # 3. 身份绑定（I9）
        expected = self.identities.get(side)
        if expected is None or msg.source != expected:
            self.rejections.append(("I9", side, msg.source))
            return self._fail(side, msg, "UNAUTHORIZED")

        # 4. Session 有效性
        if not self.session.is_active():
            return self._fail(side, msg, "SESSION_EXPIRED")

        # 5. 序列检查（S1–S5）
        cls = self.session.receiver.classify(msg)
        if cls == "duplicate":
            self.duplicates += 1
            return self._finish(side, self._on_duplicate(side, msg))
        if cls != "accept":
            return self._fail(side, msg, "SEQ_OUT_OF_ORDER")
        self.session.receiver.apply(msg)
        self.sm.record.cursors[msg.source] = msg.seq

        # 6. 类型分发
        if msg.type == "event":
            return self._finish(side, self._on_event(side, msg))
        if msg.type == "action":
            return self._finish(side, self._on_action(side, msg))
        if msg.type == "result":
            return self._finish(side, self._on_result(side, msg))
        return self._fail(side, msg, "INVALID_MESSAGE", "unknown type")

    def _finish(self, side: str, outbound: List[Message]) -> List[Message]:
        for m in outbound:
            self.outbound[self._other(side)].append(m.to_dict())
        return outbound

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

        # ④ Session 状态匹配（SUSPENDED 时禁止业务 action 执行）
        if self.sm.state == "SUSPENDED" and entry.risk in ("L2", "L3", "L4"):
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
            self._audit_action(msg, entry, verdict="permitted", rule="session_control")
            return [make_result(self.session_id, "gateway", "ok", msg.id,
                                data={"outcome": outcome})]

        # ⑥ 策略评估（§9.2 风险分级）
        policy_ctx = self._policy_context(params)
        decision, rule = self.policy.evaluate(name, entry, policy_ctx)
        if decision == PolicyDecision.REJECT:
            self.rejections.append(("POLICY", msg.id, rule))
            return [make_result(self.session_id, "gateway", "rejected",
                                msg.id, code="policy_violation", message=rule)]

        if decision == PolicyDecision.REQUIRE_HUMAN:
            return self._create_human_task_and_suspend(msg, entry, rule)

        # ⑦ 审计 + 调度 + 转发
        self._audit_action(msg, entry, verdict="permitted", rule=rule)
        self.retry_scheduler.schedule(msg, entry)
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
        for src, role in self.identities.items():
            if role == "executor":
                return src
        return "executor"

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
        })
        return s