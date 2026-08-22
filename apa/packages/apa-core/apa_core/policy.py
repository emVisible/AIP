"""apa-core: 策略引擎（设计文档 §9.2 风险分级 + §8.2 校验链第 ④ 步）。

风险分级默认策略：
  L0 只读/零副作用       → PERMIT
  L1 低风险可撤销        → PERMIT（写审计）
  L2 中等风险可回滚      → PERMIT（写审计，可告警）
  L3 高风险难以回滚      → REQUIRE_HUMAN（挂起等待人工确认）
  L4 极高风险不可逆      → REQUIRE_HUMAN（强制双人审批）

策略可覆盖：允许将特定 action 提升到 REQUIRE_HUMAN 或 REJECT，
或通过 requires_approval_at 将 L0-L2 的动作按注册表声明挂起。
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from .registry import RegistryEntry

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


class PolicyDecision(str, Enum):
    PERMIT = "permit"
    REQUIRE_HUMAN = "require_human"
    REJECT = "reject"


class PolicyConfig:
    """策略配置。rule 列表按顺序求值，首个命中的规则决定结果。"""

    def __init__(
        self,
        rules: Optional[List[dict]] = None,
        *,
        require_approval: Optional[List[str]] = None,
        deny: Optional[List[str]] = None,
        default: str = "auto",
    ) -> None:
        # default: "auto"（按风险分级）| "permit" | "deny"
        self.default = default
        self.require_approval = set(require_approval or [])
        self.deny = set(deny or [])
        self.rules = rules or []

    @classmethod
    def permissive(cls) -> "PolicyConfig":
        return cls(default="permit")

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PolicyConfig":
        if yaml is None:
            raise RuntimeError("PyYAML is required")
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "PolicyConfig":
        return cls(
            rules=data.get("rules"),
            require_approval=data.get("require_approval"),
            deny=data.get("deny"),
            default=data.get("default", "auto"),
        )

    # --- 求值 ----------------------------------------------------------------
    def evaluate(
        self, action_name: str, entry: RegistryEntry, context: Optional[dict] = None
    ) -> tuple[PolicyDecision, str]:
        """返回 (决策, 命中的规则名)。context 供自定义规则使用（如金额阈值）。"""
        if action_name in self.deny:
            return PolicyDecision.REJECT, "deny_list"
        if action_name in self.require_approval:
            return PolicyDecision.REQUIRE_HUMAN, "require_approval"

        for rule in self.rules:
            if rule.get("action") != action_name:
                continue
            if rule.get("when"):
                if not self._match(rule["when"], context or {}):
                    continue
            decision = rule.get("decision")
            if decision in ("permit", "require_human", "reject"):
                return PolicyDecision(decision), rule.get("name", "rule")
            raise ValueError(f"invalid decision {decision!r}")

        # 注册表声明的审批阈值（requires_approval_at）
        if entry.requires_approval_at:
            return PolicyDecision.REQUIRE_HUMAN, f"requires_approval_at:{entry.requires_approval_at}"

        # 默认：按风险分级
        if self.default == "permit":
            return PolicyDecision.PERMIT, "default_permit"
        if self.default == "deny":
            return PolicyDecision.REJECT, "default_deny"
        if entry.risk in ("L3", "L4"):
            return PolicyDecision.REQUIRE_HUMAN, f"risk:{entry.risk}"
        return PolicyDecision.PERMIT, f"risk:{entry.risk}"

    @staticmethod
    def _match(cond: dict, ctx: dict) -> bool:
        """极简条件匹配：{ field: value } 全部相等才命中。"""
        for k, v in cond.items():
            if k not in ctx or ctx[k] != v:
                return False
        return True

    def describe(self) -> dict:
        return {
            "default": self.default,
            "require_approval": sorted(self.require_approval),
            "deny": sorted(self.deny),
            "rules": self.rules,
        }