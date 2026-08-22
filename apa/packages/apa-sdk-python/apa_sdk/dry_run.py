"""apa-sdk: Dry Run 模式（设计文档 §12.2）。

L1+ 风险动作模拟执行，返回虚构的 ok 结果。
用途：流程测试、新员工培训、审计演练。
"""
from __future__ import annotations

from typing import Tuple

from apa_core.registry import ActionRegistry

from .executor_base import AIPExecutor

RISK_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4}


class DryRunExecutor(AIPExecutor):
    def __init__(
        self,
        source: str,
        session_id: str,
        transport=None,
        *,
        registry: ActionRegistry,
        dry_run: bool = False,
        **kw,
    ) -> None:
        super().__init__(source, session_id, transport, **kw)
        self.registry = registry
        self.dry_run = dry_run
        self.dry_run_log: list = []

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        entry = self.registry.get(name)
        if self.dry_run and entry is not None and RISK_RANK[entry.risk] >= 1:
            self.dry_run_log.append({"action": name, "params": params,
                                     "would_risk": entry.risk})
            return True, {"dry_run": True, "simulated": True}
        return self._real_execute(name, params)

    def _real_execute(self, name: str, params: dict) -> Tuple[bool, dict]:
        raise NotImplementedError