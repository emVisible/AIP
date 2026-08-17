"""AIP Kernel v0.1 — message construction and validation (SPEC §3–§6)."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TYPES: tuple = ("event", "action", "result", "error")
REQUIRED_FIELDS: tuple = ("v", "type", "id", "session", "seq", "source", "payload")

KERNEL_ERROR_CODES: frozenset = frozenset({
    "INVALID_MESSAGE", "INVALID_ACTION", "UNSUPPORTED_VERSION", "UNAUTHORIZED",
    "SEQ_OUT_OF_ORDER", "DUPLICATE_MESSAGE", "SESSION_EXPIRED",
    "AGENT_UNAVAILABLE", "RPA_UNAVAILABLE", "INTERNAL_ERROR",
})

NON_TERMINAL_STATUS: tuple = ("accepted", "running")
TERMINAL_STATUS: tuple = ("ok", "failed", "timeout", "rejected")
ALL_STATUS: tuple = NON_TERMINAL_STATUS + TERMINAL_STATUS


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class Message:
    """One AIP envelope (SPEC §3.2)."""
    v: int = 1
    type: str = "event"
    id: str = ""
    in_reply_to: Optional[str] = None
    session: str = ""
    seq: int = 1
    ts: int = 0
    source: str = ""
    payload: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(
            v=d.get("v", 1),
            type=d.get("type", ""),
            id=d.get("id", ""),
            in_reply_to=d.get("in_reply_to"),
            session=d.get("session", ""),
            seq=d.get("seq", 1),
            ts=d.get("ts", 0),
            source=d.get("source", ""),
            payload=d.get("payload", {}),
        )

    def to_dict(self) -> dict:
        return {
            "v": self.v,
            "type": self.type,
            "id": self.id,
            "in_reply_to": self.in_reply_to,
            "session": self.session,
            "seq": self.seq,
            "ts": self.ts,
            "source": self.source,
            "payload": self.payload,
        }


def _base(
    type_: str,
    session: str,
    source: str,
    prefix: str,
    seq: Optional[int],
    id_: Optional[str],
    ts: Optional[int],
    in_reply_to: Optional[str] = None,
) -> Message:
    # seq=0 means "unassigned"; peers assign the next per-stream value.
    return Message(
        type=type_,
        id=id_ or new_id(prefix),
        session=session,
        seq=seq if seq is not None else 0,
        ts=ts if ts is not None else now_ms(),
        source=source,
        in_reply_to=in_reply_to,
    )


def make_event(
    session: str,
    source: str,
    name: str,
    data: Optional[dict] = None,
    *,
    seq: Optional[int] = None,
    id: Optional[str] = None,
    ts: Optional[int] = None,
) -> Message:
    """Build an `event` (SPEC §4.1). Events never carry in_reply_to."""
    payload: Dict[str, Any] = {"name": name}
    if data is not None:
        payload["data"] = data
    msg = _base("event", session, source, "evt", seq, id, ts)
    msg.payload = payload
    return msg


def make_action(
    session: str,
    source: str,
    name: str,
    target: Optional[str] = None,
    params: Optional[dict] = None,
    expect: Optional[dict] = None,
    *,
    seq: Optional[int] = None,
    id: Optional[str] = None,
    ts: Optional[int] = None,
    in_reply_to: Optional[str] = None,
) -> Message:
    """Build an `action` (SPEC §4.2). Never carries idempotency/risk overrides."""
    payload: Dict[str, Any] = {"name": name}
    if target is not None:
        payload["target"] = target
    if params is not None:
        payload["params"] = params
    if expect is not None:
        payload["expect"] = expect
    msg = _base("action", session, source, "act", seq, id, ts, in_reply_to)
    msg.payload = payload
    return msg


def make_result(
    session: str,
    source: str,
    status: str,
    in_reply_to: str,
    *,
    data: Optional[dict] = None,
    code: Optional[str] = None,
    message: Optional[str] = None,
    duplicate: bool = False,
    original_result_id: Optional[str] = None,
    retry: Optional[dict] = None,
    seq: Optional[int] = None,
    id: Optional[str] = None,
    ts: Optional[int] = None,
) -> Message:
    """Build a `result` (SPEC §4.3). status MUST be one of ALL_STATUS."""
    payload: Dict[str, Any] = {"status": status}
    if code is not None:
        payload["code"] = code
    if message is not None:
        payload["message"] = message
    if data is not None:
        payload["data"] = data
    if duplicate:
        payload["duplicate"] = True
    if original_result_id is not None:
        payload["original_result_id"] = original_result_id
    if retry is not None:
        payload["retry"] = retry
    msg = _base("result", session, source, "res", seq, id, ts, in_reply_to)
    msg.payload = payload
    return msg


def make_error(
    session: str,
    source: str,
    code: str,
    *,
    message: Optional[str] = None,
    retry: Optional[dict] = None,
    in_reply_to: Optional[str] = None,
    seq: Optional[int] = None,
    id: Optional[str] = None,
    ts: Optional[int] = None,
) -> Message:
    """Build an `error` (SPEC §4.5). code MUST be a kernel error code."""
    payload: Dict[str, Any] = {"code": code}
    if message is not None:
        payload["message"] = message
    if retry is not None:
        payload["retry"] = retry
    msg = _base("error", session, source, "err", seq, id, ts, in_reply_to)
    msg.payload = payload
    return msg


def validate_message(msg: Message) -> List[str]:
    """Cheap structural checks (schema/aip.json is the authoritative validator)."""
    errors: List[str] = []
    if msg.v != 1:
        errors.append("UNSUPPORTED_VERSION")
    if msg.type not in TYPES:
        errors.append("INVALID_MESSAGE: unknown type")
    for field_ in REQUIRED_FIELDS:
        if getattr(msg, field_, None) in (None, ""):
            errors.append(f"INVALID_MESSAGE: missing {field_}")
    if msg.type == "event" and msg.in_reply_to is not None:
        errors.append("INVALID_MESSAGE: event must not carry in_reply_to")
    if msg.type == "result":
        if msg.in_reply_to is None:
            errors.append("INVALID_MESSAGE: result must reference an action id")
        if msg.payload.get("status") not in ALL_STATUS:
            errors.append("INVALID_MESSAGE: unknown result status")
    if msg.type == "error" and msg.payload.get("code") not in KERNEL_ERROR_CODES:
        errors.append("INVALID_MESSAGE: unknown error code")
    return errors