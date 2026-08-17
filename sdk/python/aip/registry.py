"""Action Registry profile (SPEC §9.3).

NOT part of the Kernel. Idempotency, timeout, and retry counts are
properties of the action definition — never per-call parameters on the
action message (SPEC §4.2). A deployment decides its registry; the
reference registry used by the conformance harness is defined in
conformance/harness.py.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ActionDef:
    name: str
    idempotency: str = "none"  # required | optional | none
    timeout_ms: int = 0        # 0 = no timeout tracking
    retries: int = 0           # delivery retries after timeout (idempotent only)
    risk: Optional[str] = None


class ActionRegistry:
    def __init__(self) -> None:
        self._defs: dict = {}

    def register(
        self,
        name: str,
        *,
        idempotency: str = "none",
        timeout_ms: int = 0,
        retries: int = 0,
        risk: Optional[str] = None,
    ) -> "ActionRegistry":
        self._defs[name] = ActionDef(name, idempotency, timeout_ms, retries, risk)
        return self

    def get(self, name: str) -> Optional[ActionDef]:
        return self._defs.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._defs