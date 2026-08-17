"""WebSocket binding (SPEC §7.1, §10 E5). Optional: pip install aip[ws].

E5 framing rule: a text frame carries exactly one JSON document. A frame
with two objects, trailing garbage, or a non-object value is a
transport-level error surfaced via on_error — never a message.
"""
import asyncio
import json
from typing import Awaitable, Callable, List, Optional, Tuple

from .messages import Message

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore


def parse_frame(text: str) -> Tuple[Optional[Message], Optional[str]]:
    """Return (message, None) or (None, error). One JSON object per frame."""
    trimmed = text.strip()
    if not trimmed:
        return None, "empty frame"
    try:
        value = json.loads(trimmed)
    except ValueError:
        return None, "invalid-json"
    if not isinstance(value, dict):
        return None, "not-a-single-object"
    return Message.from_dict(value), None


async def _maybe_await(fn: Callable, *args) -> None:
    result = fn(*args)
    if asyncio.iscoroutine(result):
        await result


class WsServer:
    """WebSocket server transport. on_message(Message) / on_error(err, frame)."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        on_message: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ) -> None:
        if websockets is None:
            raise ImportError("pip install aip[ws] (websockets)")
        self.host, self.requested_port = host, port
        self.on_message = on_message
        self.on_error = on_error
        self._server = None
        self._clients: List = []

    async def start(self) -> int:
        self._server = await websockets.serve(self._handler, self.host, self.requested_port)
        return self.port()

    async def _handler(self, ws) -> None:
        self._clients.append(ws)
        try:
            async for frame in ws:
                msg, err = parse_frame(frame)
                if err is not None:
                    if self.on_error is not None:
                        await _maybe_await(self.on_error, err, frame)
                elif self.on_message is not None:
                    await _maybe_await(self.on_message, msg)
        finally:
            if ws in self._clients:
                self._clients.remove(ws)

    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            return 0
        return self._server.sockets[0].getsockname()[1]

    async def send(self, message: Message) -> None:
        data = json.dumps(message.to_dict(), ensure_ascii=False)
        for ws in list(self._clients):
            await ws.send(data)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


class WsClient:
    """WebSocket client transport. on_message(Message) / on_error(err, frame)."""

    def __init__(
        self,
        url: str,
        on_message: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ) -> None:
        if websockets is None:
            raise ImportError("pip install aip[ws] (websockets)")
        self.url = url
        self.on_message = on_message
        self.on_error = on_error
        self._ws = None

    async def connect(self) -> "WsClient":
        self._ws = await websockets.connect(self.url)
        return self

    async def run(self) -> None:
        """Receive frames until the connection closes."""
        async for frame in self._ws:
            msg, err = parse_frame(frame)
            if err is not None:
                if self.on_error is not None:
                    await _maybe_await(self.on_error, err, frame)
            elif self.on_message is not None:
                await _maybe_await(self.on_message, msg)

    async def send(self, message: Message) -> None:
        await self._ws.send(json.dumps(message.to_dict(), ensure_ascii=False))

    async def send_text(self, text: str) -> None:
        """Raw frame — for fault-injection tests (e.g. E5)."""
        await self._ws.send(text)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()