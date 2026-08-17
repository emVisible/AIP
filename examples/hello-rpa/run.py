"""hello-rpa: end-to-end AIP loop over an in-memory transport.

Flow (SPEC Appendix A):

    executor --event button.appeared--> gateway --event--> agent
    agent   --action browser.click-----> gateway --action--> executor
    executor --result accepted/running/ok-> gateway --result--> agent
    executor --event order.requires_review (context ref only)
    agent   --action context.get (fields on demand) --> executor
    executor --result ok (only requested fields) ----> agent
    agent   --action erp.order.approve-> gateway --action--> executor
    executor --result ok---------------> gateway --result--> agent
    executor --event order.submitted---> gateway --event--> agent  (done)

No chat, no long context, no bulk payloads: the order data never leaves
the executor's context store except for the fields the agent asks for.
"""
import sys
from pathlib import Path
from typing import Callable, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "sdk" / "python"))

from aip import AIPPeer

from agent import Agent
from executor import Executor
from gateway import Gateway

SESSION = "s_demo"
LOG: List[str] = []


class Pipe:
    """One-direction transport for a peer: send() hands the message to a sink."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.into: Callable[[dict], None] | None = None

    def send(self, message: dict) -> None:
        LOG.append(f"{self.name} -> gateway: {message['type']} {message['payload']}")
        if self.into is not None:
            self.into(message)


def main() -> int:
    gateway = Gateway(SESSION, identities={"executor": "rpa_001", "agent": "agent_001"})

    exec_out = Pipe("executor")
    agent_out = Pipe("agent")

    executor = Executor(AIPPeer(source="rpa_001", session_id=SESSION, transport=exec_out))
    agent = Agent(AIPPeer(source="agent_001", session_id=SESSION, transport=agent_out))

    def fwd(side: str, peer) -> Callable[[dict], None]:
        def handler(raw: dict) -> None:
            LOG.append(f"gateway -> {side}: {raw['type']} {raw['payload']}")
            peer.on_message(raw)
        return handler

    gateway.set_handler("executor", fwd("executor", executor))
    gateway.set_handler("agent", fwd("agent", agent))
    exec_out.into = lambda raw: gateway.deliver("executor", raw)
    agent_out.into = lambda raw: gateway.deliver("agent", raw)

    print("== hello-rpa: AIP loop (in-memory transport) ==")
    executor.peer.send_event("button.appeared", data={"id": "confirm", "enabled": True})

    print("\nmessage log:")
    for line in LOG:
        print(f"  {line}")

    print("\nagent steps:")
    for step in agent.steps:
        print(f"  {step}")
    print("executor completions:", executor.completed)
    print("gateway executions:", gateway.executions, "| cursors:", gateway.hello()["cursors"])

    ok = agent.done and executor.completed == ["click(confirm)", "approve(A12345)"]
    print("\nRESULT:", "OK — order submitted" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())