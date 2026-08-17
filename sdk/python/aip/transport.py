"""Transport abstraction (SPEC §7). v0.1 ships an in-memory duplex link."""
from typing import Callable, Dict, List


class Endpoint:
    """A send/receive endpoint with an attachable outbound callback."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.inbox: List[dict] = []
        self._out: Callable[[dict], None] | None = None

    def attach(self, out: Callable[[dict], None]) -> None:
        self._out = out

    def send(self, message: dict) -> None:
        self.inbox.append(message)
        if self._out is not None:
            self._out(message)

    def drain(self) -> List[dict]:
        batch, self.inbox = self.inbox, []
        return batch


class Wire:
    """Bi-directional link between two Endpoints."""

    def __init__(self) -> None:
        self.a = Endpoint("wire.a")
        self.b = Endpoint("wire.b")
        self.a.attach(self.b.send)
        self.b.attach(self.a.send)

    @property
    def left(self) -> Endpoint:
        return self.a

    @property
    def right(self) -> Endpoint:
        return self.b


def connect_peers(left_endpoint: Endpoint, right_endpoint: Endpoint) -> None:
    """Connect two existing endpoints to each other."""
    left_endpoint.attach(right_endpoint.send)
    right_endpoint.attach(left_endpoint.send)