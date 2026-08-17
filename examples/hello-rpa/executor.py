"""hello-rpa executor: a scripted RPA that reacts to actions.

Emits semantic events, acknowledges actions with accepted/running, and
reports a terminal result. Owns the Context-on-Demand store (SPEC §9.2):
order data is addressable by ref, and `context.get` returns only the
fields the decision engine asks for. Zero AI — this is the execution side.
"""
from typing import List

from aip import AIPPeer, ContextStore, Message


class Executor:
    def __init__(self, peer: AIPPeer) -> None:
        self.peer = peer
        self.completed: List[str] = []
        self.store = ContextStore()
        self.store.put(
            "ctx_order_1",
            {"order_id": "A12345", "status": "pending", "total": 299.0, "customer": "c_001"},
        )

    def on_message(self, raw: dict) -> None:
        cls, msg = self.peer.handle(raw)
        if cls != "accept":
            return  # duplicate/stale/gap are handled by the receiver rules
        if msg.type == "action":
            self._execute(msg)

    def _execute(self, msg: Message) -> None:
        name = msg.payload.get("name", "")
        target = msg.payload.get("target", "")
        params = msg.payload.get("params", {})
        self.peer.send_result("accepted", in_reply_to=msg.id)
        self.peer.send_result("running", in_reply_to=msg.id)

        if name == "browser.click":
            self.completed.append(f"click({target})")
            self.peer.send_result("ok", in_reply_to=msg.id, data={"page": "payment"})
            self.peer.send_event("page.changed", data={"page": "payment"})
            # No bulk order data: just a reference + the available choices.
            self.peer.send_event(
                "order.requires_review",
                data={
                    "context": "ctx_order_1",
                    "available_actions": ["approve", "reject"],
                },
            )
        elif name == "context.get":
            ref = params.get("ref", "")
            fields = params.get("fields")
            data, err = self.store.get(ref, fields)
            if err:
                self.peer.send_result("failed", in_reply_to=msg.id, code=err)
            else:
                self.peer.send_result("ok", in_reply_to=msg.id, data={"ref": ref, "data": data})
        elif name == "erp.order.approve":
            self.completed.append(f"approve({target})")
            self.peer.send_result("ok", in_reply_to=msg.id, data={"order_id": target})
            self.peer.send_event("order.submitted", data={"order_id": target})
        else:
            self.peer.send_result(
                "failed", in_reply_to=msg.id,
                code="unknown_action", retry={"allowed": False},
            )