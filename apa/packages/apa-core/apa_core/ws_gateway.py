"""apa-core: WebSocket 独立网关（设计文档 §8/§13，AIP SPEC §7.1 E5 绑定）。

外部 Decision Engine（dsh 插件、任意 OpenAI-compatible Agent）与远程
Executor 经 WS 接入。绑定层协议（不消耗 AIP seq）：

  首帧  {"type":"hello","role":"executor"|"agent","source":"<id>",
         "cursors":{"<source>":<seq>}}          ← 重连时带游标（D1）
    ←   {"type":"hello","session":"...","cursors":{...}}
        随后网关按游标补发缓冲消息（精确恢复，I3）
  数据帧 一条 AIP 消息 JSON（E5：一帧一对象）
  心跳  {"type":"ping"} → {"type":"pong","session":...}（D4）

身份绑定（I9）：hello 的 role/source 必须匹配 identities[role]，否则拒绝并断开。
"""
from __future__ import annotations

import asyncio
import json
from typing import Dict, List, Optional

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None

from .gateway import APAGateway


class WsGatewayServer:
    """独立网关 + §10.3 多 Bot 域路由。

    hello 可声明 "domains": ["browser", ...]；action 出站按 Registry 的
    executor_domain 路由到声明了该域能力的连接；无匹配时广播全部 executor。
    """

    def __init__(
        self,
        gateway: APAGateway,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        if websockets is None:
            raise ImportError("pip install websockets")
        self.gateway = gateway
        self.host = host
        self.port_requested = port
        # side -> [ws]；executor 额外维护 (source, domains, ws)
        self.conns: Dict[str, list] = {"executor": [], "agent": []}
        self.executor_meta: Dict[object, dict] = {}  # id(ws) -> {source, domains}
        self._queues: Dict[str, asyncio.Queue] = {
            "executor": asyncio.Queue(), "agent": asyncio.Queue()}
        self._tasks: List[asyncio.Task] = []
        self._server = None
        for side in ("executor", "agent"):
            self.gateway.set_handler(side, self._make_enqueuer(side))

    def _make_enqueuer(self, side: str):
        def handler(raw: dict) -> None:
            self._queues[side].put_nowait(raw)
        return handler

    async def start(self) -> int:
        self._server = await websockets.serve(
            self._client_handler, self.host, self.port_requested)
        for side in ("executor", "agent"):
            self._tasks.append(asyncio.create_task(self._pump(side)))
        return self.port()

    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            return 0
        return self._server.sockets[0].getsockname()[1]

    async def serve_forever(self) -> None:
        if self._server is not None:
            await self._server.wait_closed()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    # --- 入站 -----------------------------------------------------------------
    async def _client_handler(self, ws) -> None:
        side: Optional[str] = None
        source: Optional[str] = None
        try:
            async for frame in ws:
                try:
                    data = json.loads(frame)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                kind = data.get("type")
                if kind == "ping":  # D4：心跳不消耗 seq
                    await ws.send(json.dumps({"type": "pong",
                                              "session": self.gateway.session_id}))
                    continue
                if kind == "hello":
                    side, source = await self._on_hello(ws, data)
                    if side is None:
                        break  # 身份不匹配：已回错误并关闭
                    continue
                if side is None or source is None:
                    continue  # 未 hello 前的裸消息忽略
                # AIP 数据帧：以声明的身份进入网关校验链
                payload = dict(data)
                payload.setdefault("source", source)
                self.gateway.deliver(side, payload)
        except Exception:  # 连接异常按断开处理
            pass
        finally:
            if side is not None and ws in self.conns[side]:
                self.conns[side].remove(ws)
                self.executor_meta.pop(id(ws), None)
                if not self.conns[side]:
                    self.gateway.disconnect(side)

    async def _on_hello(self, ws, data: dict) -> tuple:
        role = data.get("role")
        source = data.get("source", "")
        expected = self.gateway.identities.get(role or "")
        if role not in ("executor", "agent") or not self.gateway._identity_ok(
                role, source):
            await ws.send(json.dumps({
                "type": "error", "code": "UNAUTHORIZED",
                "message": f"role/source mismatch: {role}/{source!r}"}))
            return None, None
        cursors = data.get("cursors") or {}
        if self.gateway.sm.state in ("INITIALIZING",):
            self.gateway.sm.start()
        self.conns[role].append(ws)
        self.executor_meta[id(ws)] = {
            "source": source,
            "domains": list(data.get("domains") or []),
        }
        self.gateway.connected[role] = True
        if role == "executor":
            if self.gateway.sm.state == "RECOVERING":
                self.gateway.sm.transition("RUNNING")  # 重连恢复（I3）
            self.gateway.sm.executor_ready(source, cursors.get(source, 0))
        await ws.send(json.dumps({
            "type": "hello", "session": self.gateway.session_id,
            "cursors": self.gateway.session.cursors()}))
        # 补发缓冲（精确恢复）；多 Bot 时按域过滤
        buffered = [raw for raw in self.gateway.outbound.get(role, [])
                    if cursors.get(raw.get("source"), 0) < raw.get("seq", 0)]
        for raw in buffered:
            if role == "executor" and len(self.conns["executor"]) > 1 \
                    and ws not in self._targets_for_action(raw):
                continue
            await ws.send(json.dumps(raw, ensure_ascii=False))
        return role, source

    # --- 出站 -----------------------------------------------------------------
    def _targets_for_action(self, raw: dict) -> list:
        """§10.3 域路由：按 Registry.executor_domain 选目标连接。

        匹配顺序：声明了该域的 executor → 未声明域的 executor（通配）→ 全部。
        """
        conns = list(self.conns["executor"])
        if len(conns) <= 1:
            return conns
        name = (raw.get("payload") or {}).get("name", "")
        entry = self.gateway.registry.get(name)
        domain = entry.executor_domain if entry else None
        if domain in (None, "", "any"):
            return conns

        def domains_of(ws) -> set:
            return set(self.executor_meta.get(id(ws), {}).get("domains", []))

        exact = [ws for ws in conns if domain in domains_of(ws)]
        if exact:
            return exact
        wildcard = [ws for ws in conns if not domains_of(ws)]
        return wildcard or conns

    async def _pump(self, side: str) -> None:
        q = self._queues[side]
        while True:
            raw = await q.get()
            frame = json.dumps(raw, ensure_ascii=False)
            targets = (self._targets_for_action(raw) if side == "executor"
                       else list(self.conns["agent"]))
            dead = []
            for ws in targets:
                try:
                    await ws.send(frame)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                if ws in self.conns[side]:
                    self.conns[side].remove(ws)
                    self.executor_meta.pop(id(ws), None)