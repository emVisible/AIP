"""AIP peer: send helpers with automatic per-stream sequence assignment.

A peer is one participant (decision engine or executor) on one side of a
session. It assigns seq per (session, source), builds messages, and can
classify inbound messages against its own receiver (SPEC §5.4).
"""
from typing import Optional

from .messages import (
    Message,
    make_action,
    make_error,
    make_event,
    make_result,
)
from .sequence import Receiver, Sequencer
from .session import Session


class AIPPeer:
    def __init__(
        self,
        source: str,
        session_id: str,
        transport=None,
        identity: Optional[str] = None,
    ) -> None:
        self.source = source
        self.session_id = session_id
        self.transport = transport
        self.identity = identity or source
        self.seq = Sequencer()
        self.receiver = Receiver()
        self.session = Session(session_id)
        self.session.receiver = self.receiver

    # --- outbound -----------------------------------------------------------
    def send(self, message: Message) -> Message:
        if not message.seq:
            message.seq = self.seq.next(self.session_id, self.source)
        if self.transport is not None:
            self.transport.send(message.to_dict())
        return message

    def send_event(self, name, data=None, **kw) -> Message:
        return self.send(make_event(self.session_id, self.source, name, data, **kw))

    def send_action(self, name, target=None, params=None, expect=None, **kw) -> Message:
        return self.send(
            make_action(self.session_id, self.source, name, target, params, expect, **kw)
        )

    def build_action(self, name, target=None, params=None, expect=None, **kw) -> Message:
        """Build an action WITHOUT sending it. Useful when the caller must
        register correlation state before delivery (a synchronous transport
        may re-enter the caller before send() returns)."""
        return make_action(self.session_id, self.source, name, target, params, expect, **kw)

    def send_result(
        self,
        status,
        in_reply_to,
        *,
        data=None,
        code=None,
        message=None,
        duplicate=False,
        original_result_id=None,
        retry=None,
        **kw,
    ) -> Message:
        return self.send(
            make_result(
                self.session_id, self.source, status, in_reply_to,
                data=data, code=code, message=message,
                duplicate=duplicate, original_result_id=original_result_id,
                retry=retry, **kw,
            )
        )

    def send_error(self, code, *, message=None, retry=None, in_reply_to=None, **kw) -> Message:
        return self.send(
            make_error(self.session_id, self.source, code, message=message,
                       retry=retry, in_reply_to=in_reply_to, **kw)
        )

    # --- inbound ------------------------------------------------------------
    def handle(self, raw: dict) -> tuple:
        """Classify an inbound message.

        Returns (classification, message) where classification is one of
        "accept", "duplicate", "stale", "gap". The caller applies side
        effects for "accept" only; "duplicate" must never be re-executed.
        """
        msg = Message.from_dict(raw)
        cls = self.receiver.classify(msg)
        if cls == "accept":
            self.receiver.apply(msg)
        return cls, msg