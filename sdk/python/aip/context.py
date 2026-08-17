"""Context-on-Demand profile (SPEC §9.2).

Context objects are addressable, versioned, and expiring. Consumers fetch
only the fields they need via the `context.get` ACTION (an ordinary action
answered by a normal result — no new message types, SPEC §4/§C.9). The
Gateway/executor owns the store; the decision engine never receives bulk
payloads.

Extension error codes: context.not_found, context.expired.
"""
from typing import Any, Dict, List, Optional, Tuple

from .clock import Clock


class ContextStore:
    def __init__(self, ttl_ms: int = 300_000, clock: Optional[Clock] = None) -> None:
        self.ttl_ms = ttl_ms
        self.clock = clock or Clock()
        self._objects: Dict[str, Dict[str, Any]] = {}

    def put(self, ref: str, data: Dict[str, Any], *, ttl_ms: Optional[int] = None) -> None:
        """Store (or update) a context object. Each put bumps its version."""
        now = self.clock.now_ms()
        ttl = ttl_ms if ttl_ms is not None else self.ttl_ms
        obj = self._objects.setdefault(ref, {"version": 0, "data": {}, "expires": 0})
        obj["version"] += 1
        obj["data"] = dict(data)
        obj["expires"] = now + ttl

    def get(
        self, ref: str, fields: Optional[List[str]] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Return (data, None) on success, or (None, error_code) on failure.

        Only requested fields are returned (missing fields are omitted);
        fields=None returns the full object.
        """
        obj = self._objects.get(ref)
        if obj is None:
            return None, "context.not_found"
        if self.clock.now_ms() > obj["expires"]:
            return None, "context.expired"
        data = obj["data"]
        if fields is None:
            return dict(data), None
        return {f: data[f] for f in fields if f in data}, None

    def version(self, ref: str) -> Optional[int]:
        obj = self._objects.get(ref)
        return obj["version"] if obj is not None else None

    def delete(self, ref: str) -> None:
        self._objects.pop(ref, None)