"""apa-core: 规则决策引擎（设计文档 §7.2 L0，0 Token）。

规则形式（§14.2 hello-rpa 的两种条件）：
    # 事件条件
    { "if": { "event": "browser.page.loaded", "url_contains": "search" },
      "then": { "action": "browser.extract", "params": {...} } }
    # 动作结果条件（含上下文数据比较 + 模板插值）
    { "if": { "action_result": "context.get", "status": "ok",
              "data": { "amount": { "lt": 100000 } } },
      "then": { "action": "erp.order.approve",
                "params": { "order_id": "{{order_id}}" } } }

params 支持 {{field}} 插值，取值来源：当前事件 data / 最近一次 context.get 结果。

契约（§7.1）：
  DE-1 只消费 terminal result（ok/failed/timeout/rejected）
  DE-2 按需 fetch 上下文，不缓存 Session 状态（C7）
  DE-3 action 只带 name/target/params（C3）
  DE-4 只在 error.retry.allowed=true 时重试，复用同一 action.id
  DE-5 不确定时创建 human.task，而不是猜测
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from aip import AIPPeer, Message

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

TEMPLATE_RE = re.compile(r"\{\{([a-zA-Z0-9_.]+)\}\}")


def lookup(ctx: Dict[str, Any], dotted: str) -> Any:
    """按 a.b.c 路径取值；缺失返回 None。"""
    value: Any = ctx
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def interpolate(template: str, ctx: Dict[str, Any]) -> str:
    def _lookup(m: re.Match) -> str:
        value = lookup(ctx, m.group(1))
        return m.group(0) if value is None else str(value)
    return TEMPLATE_RE.sub(_lookup, template)


def _compare(value: Any, cond: Any) -> bool:
    """支持 {lt,le,gt,ge,ne,eq} 与直接相等比较。"""
    if isinstance(cond, dict) and set(cond) <= {"lt", "le", "gt", "ge", "ne", "eq"}:
        try:
            if "lt" in cond and not (value < cond["lt"]):
                return False
            if "le" in cond and not (value <= cond["le"]):
                return False
            if "gt" in cond and not (value > cond["gt"]):
                return False
            if "ge" in cond and not (value >= cond["ge"]):
                return False
            if "ne" in cond and value == cond["ne"]:
                return False
            if "eq" in cond and value != cond["eq"]:
                return False
        except TypeError:
            return False
        return True
    return value == cond


class RuleEngine:
    def __init__(self, rules: List[dict] | None = None) -> None:
        self.rules: List[dict] = rules or []
        self.matched: List[dict] = []

    @classmethod
    def from_yaml(cls, path: str) -> "RuleEngine":
        if yaml is None:
            raise RuntimeError("PyYAML is required")
        import pathlib
        data = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
        return cls(data if isinstance(data, list) else data.get("rules", []))

    def add(self, rule: dict) -> None:
        self.rules.append(rule)

    # --- 匹配 --------------------------------------------------------------
    def evaluate_event(self, event_name: str, data: dict) -> Optional[dict]:
        for rule in self.rules:
            cond = rule.get("if", {})
            if "event" not in cond or "action_result" in cond:
                continue
            if cond["event"] != event_name:
                continue
            if not self._match_extra(cond, data):
                continue
            self.matched.append(rule)
            return self._then(rule)
        return None

    def evaluate_result(self, action_name: str, status: str, data: dict) -> Optional[dict]:
        for rule in self.rules:
            cond = rule.get("if", {})
            if cond.get("action_result") != action_name:
                continue
            if "status" in cond and cond["status"] != status:
                continue
            if not self._match_extra(cond, data):
                continue
            self.matched.append(rule)
            return self._then(rule)
        return None

    def _match_extra(self, cond: dict, data: dict) -> bool:
        field_map = {"url_contains": "url", "title_contains": "title",
                     "text_contains": "text"}
        for key in ("url_contains", "title_contains", "text_contains"):
            if key in cond and cond[key] not in data.get(field_map[key], ""):
                return False
        for k, v in cond.get("data", {}).items():
            # {"present": true}：字段存在且非空
            if isinstance(v, dict) and v.get("present") is True:
                if k not in data or data[k] in (None, "", []):
                    return False
                continue
            if k not in data or not _compare(data[k], v):
                return False
        return True

    def _then(self, rule: dict) -> dict:
        then = dict(rule.get("then", {}))
        then["_rule"] = rule.get("name", "")
        then["_once"] = bool(rule.get("once", False))
        return then


class RuleBasedAgent:
    """基于规则的 Decision Engine（§7.3 的 Python 对应物）。

    无状态（C7）。决策从「当前事件 + 按需 fetch 的上下文」出发。
    """

    def __init__(
        self,
        peer: AIPPeer,
        rules: List[dict] | RuleEngine,
        *,
        on_done: Optional[Callable[[], None]] = None,
    ) -> None:
        self.peer = peer
        self.engine = rules if isinstance(rules, RuleEngine) else RuleEngine(rules)
        self.steps: List[str] = []
        self.done = False
        self.on_done = on_done
        self.pending_context: Optional[str] = None
        self.sent: Dict[str, str] = {}      # action_id -> action name
        self.ctx: Dict[str, Any] = {}       # 最近事件 data + context.get 结果
        self._fired: set = set()            # (rule_name, trigger_id) 防重复触发

    # --- inbound ------------------------------------------------------------
    def on_message(self, raw: dict) -> None:
        cls, msg = self.peer.handle(raw)
        if cls != "accept":
            return
        if msg.type == "event":
            self._on_event(msg)
        elif msg.type == "result":
            self._on_result(msg)

    def _on_event(self, msg: Message) -> None:
        name = msg.payload.get("name", "")
        data = msg.payload.get("data", {})
        self.ctx.update(data if isinstance(data, dict) else {})
        then = self.engine.evaluate_event(name, data)
        if then:
            if not self._should_fire(then):
                return
            self._apply_then(then, in_reply_to=msg.id)

    def _should_fire(self, then: dict) -> bool:
        """once 规则整个 Session 只执行一次（防重复触发）。"""
        key = ("once", then.get("_rule", ""))
        if then.get("_once") and key in self._fired:
            return False
        self._fired.add(key)
        return True

    def _on_result(self, msg: Message) -> None:
        status = msg.payload.get("status", "")
        if status == "rejected":
            self.steps.append(f"result: rejected ({msg.payload.get('code')}) — stop")
            self._finish()
            return
        if status not in ("ok", "failed", "timeout"):
            return  # 非终态，继续等待（DE-1）
        action_id = msg.in_reply_to or ""
        action_name = self.sent.get(action_id, "")
        result_data = msg.payload.get("data") or {}
        self.ctx.update(result_data)  # 任何终态结果的数据都可被模板引用
        if action_name == "context.get" and status == "ok":
            data = result_data.get("data", {})
            self.ctx.update(data if isinstance(data, dict) else {})
            then = self.engine.evaluate_result("context.get", status, data)
            if then and self._should_fire(then):
                self._apply_then(then, in_reply_to=msg.id)
            return
        if action_name == "context.get" and status != "ok":
            # CoD 取数失败：默认停止而非悬挂（DE-5 精神：不猜测）
            self.steps.append(f"result: context.get {status} — stop")
            self._finish(failure=f"context.get {status}")
            return
        then = self.engine.evaluate_result(action_name, status, result_data)
        if then and self._should_fire(then):
            self._apply_then(then, in_reply_to=msg.id)

    def _apply_then(self, then: dict, *, in_reply_to: Optional[str] = None) -> None:
        action = then.get("action", "")
        params = then.get("params", {})
        target = then.get("target")
        rule = then.get("_rule", "")
        params = self._interpolate_params(params)
        self.steps.append(f"rule[{rule or action}]: {action} {params or ''}")

        if action == "session.complete":
            act = self.peer.build_action(
                "session.complete",
                params={"outcome": params.get("outcome", "success")},
                in_reply_to=in_reply_to,
            )
            self.sent[act.id] = "session.complete"
            self.peer.send(act)
            self._finish()
            return

        act = self.peer.build_action(
            action, target=target, params=params or None, in_reply_to=in_reply_to)
        self.sent[act.id] = action
        self.peer.send(act)

    def _interpolate_params(self, params: dict) -> dict:
        out: Dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, str):
                m = TEMPLATE_RE.fullmatch(v)
                if m is not None:
                    # 整值模板：保留原生类型（number/bool/list…）
                    native = lookup(self.ctx, m.group(1))
                    out[k] = v if native is None else native
                else:
                    out[k] = interpolate(v, self.ctx)
            elif isinstance(v, dict):
                out[k] = self._interpolate_params(v)
            else:
                out[k] = v
        return out

    # --- lifecycle ----------------------------------------------------------
    def _finish(self, failure: Optional[str] = None) -> None:
        self.done = True
        self.steps.append("done" if not failure else f"done (failed: {failure})")
        if self.on_done:
            self.on_done()

    def summary(self) -> dict:
        return {
            "done": self.done,
            "steps": list(self.steps),
            "matched_rules": len(self.engine.matched),
        }