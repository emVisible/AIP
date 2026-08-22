"""apa-core: Zero-LLM Cascade 决策代理（设计文档 §7.2）。

    L0 确定性规则（0 Token，<1ms）→ 未命中
    L1/L2 OpenAI-compatible 模型（100–3000 Token/决策，事件 data <4KB）
    L3  Human-in-the-Loop（DE-5：不确定时创建 human.task 而不是猜测）

契约（§7.1）：DE-1 只消费 terminal result；DE-2 不缓存 Session 状态（C7）；
DE-3 action 只带 name/target/params（C3 由 Gateway 兜底）；DE-5 不确定转人工。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from aip import AIPPeer

from .llm import LLMClient
from .rules import RuleBasedAgent, RuleEngine


class CascadingAgent(RuleBasedAgent):
    """规则优先；未命中走模型；模型不确定转人工。"""

    def __init__(
        self,
        peer: AIPPeer,
        rules: List[dict] | RuleEngine,
        llm: LLMClient,
        *,
        allowed_actions: Optional[List[str]] = None,
        max_llm_decisions: int = 20,
        think_events: Optional[set] = None,
        on_done=None,
    ) -> None:
        super().__init__(peer, rules, on_done=on_done)
        self.llm = llm
        self.allowed_actions = list(allowed_actions or [])
        self.max_llm_decisions = max_llm_decisions
        self.think_events = set(think_events or set())
        self.stats: Dict[str, int] = {"L0": 0, "L1": 0, "L2": 0,
                                      "human": 0, "unhandled": 0}
        self.decisions: List[dict] = []

    # --- 决策主入口 ------------------------------------------------------------
    def _on_event(self, msg) -> None:
        name = msg.payload.get("name", "")
        data = msg.payload.get("data", {})
        self.ctx.update(data if isinstance(data, dict) else {})

        # L0：确定性规则
        then = self.engine.evaluate_event(name, data)
        if then:
            if not self._should_fire(then):
                return
            self.stats["L0"] += 1
            self.decisions.append({"level": "L0", "event": name,
                                   "rule": then.get("_rule", ""),
                                   "action": then.get("action")})
            self._apply_then(then, in_reply_to=msg.id)
            return

        # 预算保护
        if self.stats["L1"] + self.stats["L2"] + self.stats["human"] \
                >= self.max_llm_decisions:
            self.stats["unhandled"] += 1
            return

        # L1/L2：模型决策（只喂事件语义与允许动作清单，<4KB）
        level = "L2" if name in self.think_events else "L1"
        decision = self.llm.decide(
            event_name=name,
            event_data=data if isinstance(data, dict) else {},
            allowed_actions=self.allowed_actions,
            context_summary=self._scalar_ctx(),
            think=level == "L2",
        )

        if "action" in decision and (not self.allowed_actions
                                     or decision["action"] in self.allowed_actions):
            self.stats[level] += 1
            self.decisions.append({"level": level, "event": name,
                                   "action": decision["action"],
                                   "params": decision.get("params", {})})
            self.steps.append(f"cascade[{level}]: {decision['action']}")
            self._apply_then({
                "_rule": f"llm:{level}",
                "action": decision["action"],
                "target": decision.get("target"),
                "params": decision.get("params", {}),
            }, in_reply_to=msg.id)
            return

        # uncertain / 越权动作名 → DE-5：人工升级（Gateway 拦截并挂起 Session）
        reason = decision.get("uncertain") or \
            f"action_not_allowed:{decision.get('action')}"
        self.stats["human"] += 1
        self.decisions.append({"level": "human", "event": name, "reason": reason})
        self.steps.append(f"cascade[{level}]: uncertain ({reason}) → human.task")
        act = self.peer.build_action("human.task.create", params={
            "task_type": "exception",
            "assignee_role": "rpa_operator",
            "context_ref": str(data.get("context", "")) if isinstance(data, dict) else "",
            "available_outcomes": ["retry", "skip", "abort"],
        }, in_reply_to=msg.id)
        self.sent[act.id] = "human.task.create"
        self.peer.send(act)

    def _scalar_ctx(self) -> Dict[str, Any]:
        """CoD 摘要：仅标量字段（不外传大对象）。"""
        return {k: v for k, v in list(self.ctx.items())[:20]
                if isinstance(v, (str, int, float, bool))}

    def summary(self) -> dict:
        s = super().summary()
        s["cascade_stats"] = dict(self.stats)
        s["decisions"] = list(self.decisions)
        return s