"""hello-rpa agent: a rule-based decision engine (zero LLM).

Consumes events and emits actions. This is the decision side — it never
holds execution state; the gateway does (SPEC §2). Order data arrives as
a context REFERENCE; the agent fetches only the fields it needs via the
context.get action (Context-on-Demand, SPEC §9.2).
"""
from typing import List, Optional

from aip import AIPPeer, Message


class Agent:
    def __init__(self, peer: AIPPeer) -> None:
        self.peer = peer
        self.steps: List[str] = []
        self.done = False
        self.pending_context: Optional[str] = None

    def on_message(self, raw: dict) -> None:
        cls, msg = self.peer.handle(raw)
        if cls != "accept":
            return
        if msg.type == "event":
            self._decide(msg)
        elif msg.type == "result":
            self._on_result(msg)

    def _decide(self, msg: Message) -> None:
        name = msg.payload.get("name", "")
        data = msg.payload.get("data", {})

        if name == "button.appeared":
            self.steps.append("decide: click confirm")
            self.peer.send_action(
                "browser.click", target="confirm",
                expect={"event": "page.changed"},
                in_reply_to=msg.id,
            )
        elif name == "order.requires_review":
            ref = data.get("context", "")
            self.steps.append(f"decide: fetch context ({ref}, on demand)")
            # Build first, register the pending correlation, THEN send: a
            # synchronous transport may deliver the executor's reply before
            # send() returns (re-entrancy), so pending must exist beforehand.
            action = self.peer.build_action(
                "context.get",
                params={"ref": ref, "fields": ["order_id", "total", "customer"]},
                in_reply_to=msg.id,
            )
            self.pending_context = action.id
            self.peer.send(action)
        elif name == "order.submitted":
            self.steps.append("decide: done")
            self.done = True

    def _on_result(self, msg: Message) -> None:
        status = msg.payload.get("status", "")
        if status == "rejected":
            self.steps.append(f"result: {msg.payload.get('code')} — stop")
            self.done = True
            return
        if status not in ("ok", "failed", "timeout"):
            return  # non-terminal (accepted/running): keep waiting
        if msg.in_reply_to != self.pending_context:
            return
        self.pending_context = None
        if status != "ok":
            self.steps.append(f"result: context.get failed — {msg.payload.get('code')} — stop")
            self.done = True
            return
        data = (msg.payload.get("data") or {}).get("data", {})
        order_id = data.get("order_id", "unknown")
        total = data.get("total", 0)
        if total < 1000:
            self.steps.append(f"decide: approve {order_id} (${total})")
            self.peer.send_action("erp.order.approve", target=order_id, in_reply_to=msg.id)
        else:
            self.steps.append(f"decide: reject {order_id} (${total}) over budget")
            self.peer.send_action("erp.order.reject", target=order_id, in_reply_to=msg.id)