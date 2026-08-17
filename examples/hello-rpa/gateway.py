"""Reference AIP gateway (SPEC §7, §8, §9).

Routes events/results from the executor to the agent and actions from the
agent to the executor; enforces per-stream ordering, duplicate/idempotency
semantics, action lifecycle (I6), source binding (I9), session expiry,
credential scanning (I10), a pluggable policy hook, and — for reference —
delivery reliability: timeout tracking, idempotent retry with the same
action id (SPEC §6.5), per-side outbound buffers for resume (SPEC §7.4),
and binding-level heartbeat.

Reference implementation. The Kernel does not require a gateway (SPEC §2);
the gateway is the only place policy and retry live.
"""
import json
import re
from typing import Callable, Dict, List, Optional

from aip import ActionRegistry, Clock, Message, Receiver, Session, make_error, make_result

CREDENTIAL_PATTERNS = [
    re.compile(r"Bearer [A-Za-z0-9._~+/=-]+"),
    re.compile(r'password"\s*[:=]', re.IGNORECASE),
    re.compile(r'Authorization"\s*[:=]', re.IGNORECASE),
    re.compile(r"api_key", re.IGNORECASE),
]


class Gateway:
    def __init__(
        self,
        session_id: str,
        *,
        policy: Optional[dict] = None,
        identities: Optional[dict] = None,
        registry: Optional[ActionRegistry] = None,
        clock: Optional[Clock] = None,
    ) -> None:
        self.session = Session(session_id)
        self.session.receiver = Receiver()
        self.policy = policy or {}
        self.identities = identities or {}
        self.registry = registry or ActionRegistry()
        self.clock = clock or Clock()
        self.emitted: List[Message] = []
        self.executions = 0
        self.rejections: List[tuple] = []
        self.duplicates = 0
        self.handlers: Dict[str, Callable[[dict], None]] = {}
        self.outbound: Dict[str, List[dict]] = {"executor": [], "agent": []}
        self.connected: Dict[str, bool] = {"executor": True, "agent": True}
        self.timers: Dict[str, int] = {}        # action_id -> expiry_ms
        self.retries_left: Dict[str, int] = {}  # action_id -> int
        self.pending: Dict[str, Message] = {}   # action_id -> last action msg
        self.forwarded_ids: List[str] = []      # every forward, incl. retries
        self.retry_events = 0

    # --- wiring ---------------------------------------------------------------
    def set_handler(self, side: str, handler: Callable[[dict], None]) -> None:
        self.handlers[side] = handler

    def deliver(self, side: str, raw: dict) -> None:
        """Called when a peer on `side` sends a message. Forwards outbound
        to the peer on the other side if that connection is up."""
        outbound = self.receive(side, raw)
        other = self._other(side)
        if not self.connected[other]:
            return
        target = self.handlers.get(other)
        if target is not None:
            for msg in outbound:
                target(msg.to_dict())

    @staticmethod
    def _other(side: str) -> str:
        return "agent" if side == "executor" else "executor"

    # --- core ----------------------------------------------------------------
    def receive(self, side: str, raw: dict) -> List[Message]:
        """Process one inbound message and return outbound messages."""
        msg = Message.from_dict(raw)
        self.emitted.append(msg)

        # 1. source binding (I9)
        expected = self.identities.get(side)
        if expected is None or msg.source != expected:
            self.rejections.append(("I9", side, msg.source))
            outbound = [make_error(msg.session, "gateway", "UNAUTHORIZED", in_reply_to=msg.id)]
            return self._finish(side, outbound)

        # 2. session expiry (K2)
        if not self.session.is_active():
            outbound = [make_error(msg.session, "gateway", "SESSION_EXPIRED", in_reply_to=msg.id)]
            return self._finish(side, outbound)

        # 3. credential scan (I10)
        if self._scan(msg):
            self.rejections.append(("I10", side, msg.id))
            outbound = [
                make_error(
                    msg.session, "gateway", "INVALID_MESSAGE",
                    in_reply_to=msg.id, message="credential-like content in payload",
                )
            ]
            return self._finish(side, outbound)

        # 4. per-stream ordering (S1–S5)
        cls = self.session.receiver.classify(msg)
        if cls == "duplicate":
            self.duplicates += 1
            return self._finish(side, self._on_duplicate(side, msg))
        if cls != "accept":
            outbound = [make_error(msg.session, "gateway", "SEQ_OUT_OF_ORDER", in_reply_to=msg.id)]
            return self._finish(side, outbound)
        self.session.receiver.apply(msg)

        # 5. route
        if msg.type == "event":
            return self._finish(side, [msg])
        if msg.type == "action":
            return self._finish(side, self._on_action(side, msg))
        if msg.type == "result":
            return self._finish(side, self._on_result(side, msg))
        return self._finish(
            side, [make_error(msg.session, "gateway", "INVALID_MESSAGE", in_reply_to=msg.id)]
        )

    def _finish(self, side: str, outbound: List[Message]) -> List[Message]:
        """Buffer outbound for resume and return it to the caller."""
        for msg in outbound:
            self.outbound[self._other(side)].append(msg.to_dict())
        return outbound

    # --- handlers -------------------------------------------------------------
    def _on_action(self, side: str, msg: Message) -> List[Message]:
        name = msg.payload.get("name", "")
        self.session.actions.register(msg.id, name, msg.source)

        # idempotency: previously settled action -> return stored outcome (A3/A4)
        outcome = self.session.actions.outcome(msg.id)
        if outcome is not None:
            status, result_id = outcome
            self.duplicates += 1
            return [
                make_result(
                    msg.session, "gateway", status, msg.id,
                    duplicate=True, original_result_id=result_id,
                )
            ]

        # policy (K4)
        verdict = self._check_policy(msg)
        if verdict:
            self.rejections.append(("POLICY", msg.id, verdict))
            return [make_result(msg.session, "gateway", "rejected", msg.id, code=verdict)]

        self._forward(msg)
        return [msg]

    def _on_result(self, side: str, msg: Message) -> List[Message]:
        status = msg.payload.get("status", "")
        action_id = msg.in_reply_to or ""
        result = self.session.actions.mark(action_id, status, msg.id)
        if result == "after_terminal":
            self.rejections.append(("I6", action_id, status))
            return []
        if result == "unknown_action":
            return [make_error(msg.session, "gateway", "INVALID_MESSAGE", in_reply_to=msg.id)]
        if status in ("ok", "failed", "timeout", "rejected"):
            self.timers.pop(action_id, None)
            self.retries_left.pop(action_id, None)
        return [msg]

    def _on_duplicate(self, side: str, msg: Message) -> List[Message]:
        # Seq-level duplicate (same id + seq). Never re-execute (I2).
        if msg.type == "action":
            outcome = self.session.actions.outcome(msg.id)
            if outcome is not None:
                status, result_id = outcome
                return [
                    make_result(
                        msg.session, "gateway", status, msg.id,
                        duplicate=True, original_result_id=result_id,
                    )
                ]
        return []

    # --- delivery reliability ---------------------------------------------------
    def _forward(self, msg: Message) -> None:
        self.executions += 1
        self.forwarded_ids.append(msg.id)
        self.pending[msg.id] = msg
        entry = self.registry.get(msg.payload.get("name", ""))
        if entry is not None and entry.timeout_ms:
            self.timers[msg.id] = self.clock.now_ms() + entry.timeout_ms
            # idempotency none => retries_left stays 0; tick marks TIMEOUT, no retry
            self.retries_left[msg.id] = entry.retries if entry.idempotency != "none" else 0

    def tick(self) -> None:
        """Advance timeouts. Call after the clock advances (or on a real timer)."""
        now = self.clock.now_ms()
        for action_id in list(self.timers):
            if now < self.timers[action_id]:
                continue
            if self.session.actions.outcome(action_id) is not None:
                del self.timers[action_id]
                self.retries_left.pop(action_id, None)
                continue
            left = self.retries_left.get(action_id, 0)
            if left > 0:
                self.retry_events += 1
                self.retries_left[action_id] = left - 1
                self._redeliver(action_id)
                entry = self.registry.get(self.pending[action_id].payload.get("name", ""))
                self.timers[action_id] = now + (entry.timeout_ms if entry else 0)
            else:
                self.session.actions.mark(action_id, "timeout")
                self.pending.pop(action_id, None)
                del self.timers[action_id]

    def _redeliver(self, action_id: str) -> None:
        msg = self.pending[action_id]
        self.executions += 1
        self.forwarded_ids.append(action_id)
        raw = msg.to_dict()
        self.outbound["executor"].append(raw)
        if self.connected["executor"] and self.handlers.get("executor"):
            self.handlers["executor"](raw)

    # --- connection lifecycle (SPEC §7.3, §7.4) ----------------------------------
    def disconnect(self, side: str) -> None:
        self.connected[side] = False

    def reconnect(self, side: str, cursors: Optional[dict] = None) -> None:
        self.connected[side] = True
        self.resume(side, cursors)

    def resume(self, side: str, cursors: Optional[dict] = None) -> None:
        """Re-deliver buffered outbound for `side` beyond its cursors.

        Resent messages keep their original id and seq, so re-delivery is
        idempotent: duplicates are discarded, settled actions return stored
        outcomes (SPEC §7.4, D2/D3).
        """
        cursors = cursors or {}
        target = self.handlers.get(side)
        if target is None:
            return
        for raw in list(self.outbound[side]):
            cur = cursors.get(raw.get("source"))
            if cur is None or raw.get("seq", 0) > cur:
                target(raw)

    def pong(self) -> dict:
        """Binding-level heartbeat reply. Heartbeats never consume seq (D4)."""
        return {"type": "pong", "session": self.session.session_id}

    # --- policy & scan ---------------------------------------------------------
    def _check_policy(self, msg: Message) -> Optional[str]:
        name = msg.payload.get("name", "")
        require = self.policy.get("require_approval") or []
        if name in require:
            return "REQUIRES_APPROVAL"
        return None

    @staticmethod
    def _scan(msg: Message) -> bool:
        try:
            blob = json.dumps(msg.payload, ensure_ascii=False)
        except (TypeError, ValueError):
            return True
        return any(p.search(blob) for p in CREDENTIAL_PATTERNS)

    # --- introspection ---------------------------------------------------------
    def hello(self) -> dict:
        """Binding-level hello: return per-stream cursors (SPEC §7.4, D1)."""
        return {"session": self.session.session_id, "cursors": self.session.cursors()}

    def applied_counts(self) -> dict:
        """Per-stream number of messages applied, for conformance assertions."""
        receiver = self.session.receiver
        return {
            source: receiver.applied_count(self.session.session_id, source)
            for source in {entry[1] for entry in receiver.history}
        }