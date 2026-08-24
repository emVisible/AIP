"""apa-core: WebSocket 独立网关（设计文档 §8/§13，AIP SPEC §7.1 E5 绑定）。

外部 Decision Engine（dsh 插件、任意 OpenAI-compatible Agent）与远程
Executor 经 WS 接入。支持：
  · 多会话池 —— 单服务同时承载多个 Session（hello.session 路由）
  · TLS（wss://，ssl_context + generate_dev_certs 开发证书，§12.1 第一层）
  · 应用级令牌准入（hello_token，与 TLS 正交）

绑定层协议（不消耗 AIP seq）：

  首帧  {"type":"hello","role":"executor"|"agent","source":"<id>",
         "session":"<sid>","cursors":{...},"domains":[...],"tenant":...,
         "token":...}                          ← 重连时带游标（D1）
    ←   {"type":"hello","session":"...","cursors":{...}}
         随后网关按游标补发缓冲消息（精确恢复，I3；多 Bot 按域过滤）
  数据帧 一条 AIP 消息 JSON（E5：一帧一对象）
  心跳  {"type":"ping"} → {"type":"pong","session":...}（D4）

身份绑定（I9）：hello 的 role/source 必须匹配 identities[role]，否则拒绝并断开。
"""
from __future__ import annotations

import asyncio
import json
import os
import ssl
from pathlib import Path
from typing import Dict, List, Optional

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None

from .gateway import APAGateway

_SIDES = ("executor", "agent")


class WsGatewayServer:
    """独立网关服务：单/多会话池 + §10.3 多 Bot 域路由。

    · 构造传单个 gateway（向后兼容）或 gateways={session_id: APAGateway}
    · hello 可声明 "domains"：action 出站按 Registry.executor_domain
      精确路由到声明了该域能力的连接；无匹配时通配 → 广播
    """

    def __init__(
        self,
        gateway: Optional[APAGateway] = None,
        *,
        gateways: Optional[Dict[str, APAGateway]] = None,
        host: str = "127.0.0.1",
        port: int = 8765,
        ssl_context: Optional["ssl.SSLContext"] = None,
        hello_token: Optional[str] = None,
        tick_interval_s: float = 1.0,
    ) -> None:
        """ssl_context 非 None 时以 wss:// 监听（§12.1 第一层）；
        hello_token 配置后 hello 帧必须携带匹配 token（与 TLS 正交）。
        tick_interval_s：后台调度循环节奏 —— 驱动 RetryScheduler 超时重试、
        session TTL 等时间性语义，使独立部署无需外部 tick 驱动。"""
        if websockets is None:
            raise ImportError("pip install websockets")
        if gateways is None:
            if gateway is None:
                raise ValueError("gateway or gateways is required")
            gateways = {gateway.session_id: gateway}
        self.gateways: Dict[str, APAGateway] = dict(gateways)
        self.host = host
        self.port_requested = port
        self.ssl_context = ssl_context
        self.hello_token = hello_token
        self.tick_interval_s = max(0.05, float(tick_interval_s))

        # 每会话独立：出站队列 / 连接表
        self._queues: Dict[str, Dict[str, asyncio.Queue]] = {
            sid: {side: asyncio.Queue() for side in _SIDES}
            for sid in self.gateways
        }
        self.conns: Dict[str, Dict[str, list]] = {
            sid: {side: [] for side in _SIDES} for sid in self.gateways
        }
        self.executor_meta: Dict[int, dict] = {}   # id(ws) -> {source, domains, session}
        self._binds: Dict[int, dict] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending_pumps: List[str] = []   # start 前注册的会话由 start 统一建泵          # id(ws) -> {gw, side, source}
        self._tasks: List[asyncio.Task] = []
        self._server = None

        for sid, gw in self.gateways.items():
            for side in _SIDES:
                gw.set_handler(side, self._make_enqueuer(sid, side))

    # ---- 动态会话注册（serve 常驻模式：会话随任务动态创建）---------------------

    def register_session(self, sid: str, gateway: APAGateway) -> bool:
        """向运行中的网关池注册新会话。已存在返回 False。

        线程模型：可在任意线程调用（dict/Queue 构造 GIL 安全；
        asyncio.Queue 的 loop 绑定推迟到首次使用，3.12 无隐患）。
        """
        if sid in self.gateways:
            return False
        self.gateways[sid] = gateway
        self._queues[sid] = {side: asyncio.Queue() for side in _SIDES}
        self.conns[sid] = {side: [] for side in _SIDES}
        for side in _SIDES:
            gateway.set_handler(side, self._make_enqueuer(sid, side))

        if self._loop is not None and self._loop.is_running():
            # 运行中注册：把建泵任务调度回网关自己的事件循环
            async def _spawn():
                for side in _SIDES:
                    self._tasks.append(asyncio.create_task(self._pump(sid, side)))
            asyncio.run_coroutine_threadsafe(_spawn(), self._loop)
        else:
            self._pending_pumps.append(sid)
        return True

    def unregister_session(self, sid: str) -> None:
        self.gateways.pop(sid, None)
        self._queues.pop(sid, None)
        self.conns.pop(sid, None)

    def agent_sources(self) -> List[str]:
        """当前已连接的 agent source 列表（跨会话）。"""
        out = []
        for sid in self.conns:
            for ws in self.conns[sid].get("agent", []):
                bind = self._binds.get(id(ws))
                if bind:
                    out.append(bind["source"])
        return out

    # 向后兼容：主网关（首个会话）
    @property
    def gateway(self) -> APAGateway:
        return next(iter(self.gateways.values()))

    def _make_enqueuer(self, gsid: str, side: str):
        """出站入队 handler。线程安全（嵌入式网关跨线程调用场景）：

        gateway 处理链可能运行在与本服务器不同的事件循环/线程
        （EmbeddedGateway 模式 C）。asyncio.Queue.put_nowait 跨线程
        不会唤醒等待中的 getter —— 必须经由 call_soon_threadsafe
        把投递调度回服务器自己的循环。
        """
        q = self._queues[gsid][side]

        def handler(raw: dict) -> None:
            loop = self._loop
            if loop is not None and loop.is_running():
                try:
                    asyncio.get_running_loop()
                    same_thread = loop is asyncio.get_running_loop()
                except RuntimeError:
                    same_thread = False
                if not same_thread:
                    loop.call_soon_threadsafe(q.put_nowait, raw)
                    return
            q.put_nowait(raw)
        return handler

    async def start(self) -> int:
        self._loop = asyncio.get_running_loop()
        self._server = await websockets.serve(
            self._client_handler, self.host, self.port_requested,
            ssl=self.ssl_context)
        for sid in self.gateways:
            for side in _SIDES:
                self._tasks.append(asyncio.create_task(self._pump(sid, side)))
        # 后台调度循环：驱动超时/重试/TTL（§8.3、§10.1）
        self._tasks.append(asyncio.create_task(self._tick_loop()))
        return self.port()

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self.tick_interval_s)
            for gw in self.gateways.values():
                gw.tick()

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
        bind: Optional[dict] = None   # {"gw", "side", "source"}
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
                    gsid = bind["gw"].session_id if bind else (
                        next(iter(self.gateways)) if len(self.gateways) == 1 else None)
                    pong = {"type": "pong"}
                    if gsid:
                        pong["session"] = gsid
                    await ws.send(json.dumps(pong))
                    continue
                if kind == "hello":
                    resolved = await self._on_hello(ws, data)
                    if resolved is None:
                        break  # 准入失败：已回错误并关闭
                    bind = resolved
                    continue
                if bind is None:
                    continue  # 未 hello 前的裸消息忽略
                payload = dict(data)
                payload.setdefault("source", bind["source"])
                bind["gw"].deliver(bind["side"], payload)
        except Exception:  # 连接异常按断开处理
            pass
        finally:
            if bind is not None:
                g, s = bind["gw"], bind["side"]
                bucket = self.conns[g.session_id][s]
                if ws in bucket:
                    bucket.remove(ws)
                self.executor_meta.pop(id(ws), None)
                self._binds.pop(id(ws), None)
                if not bucket:
                    g.disconnect(s)

    async def _on_hello(self, ws, data: dict) -> Optional[dict]:
        # 会话路由（多会话池）；单网关时缺省 session 向后兼容
        session = data.get("session") or (
            next(iter(self.gateways)) if len(self.gateways) == 1 else "")
        gw = self.gateways.get(session)
        if gw is None:
            await ws.send(json.dumps({
                "type": "error", "code": "INVALID_MESSAGE",
                "message": f"unknown session {data.get('session')!r}"}))
            return None
        # 应用级令牌（§12.1 第一层的补充准入）
        if self.hello_token is not None and data.get("token") != self.hello_token:
            await ws.send(json.dumps({
                "type": "error", "code": "UNAUTHORIZED",
                "message": "invalid or missing token"}))
            return None
        role = data.get("role")
        source = data.get("source", "")
        # 租户绑定（§12.1：Session 不可跨租户）
        expected_tenant = gw.sm.record.tenant_id
        if expected_tenant and data.get("tenant") != expected_tenant:
            await ws.send(json.dumps({
                "type": "error", "code": "UNAUTHORIZED",
                "message": f"tenant mismatch: {data.get('tenant')!r}"}))
            return None
        expected = gw.identities.get(role or "")
        if role not in _SIDES or not gw._identity_ok(role, source):
            await ws.send(json.dumps({
                "type": "error", "code": "UNAUTHORIZED",
                "message": f"role/source mismatch: {role}/{source!r}"}))
            return None
        cursors = data.get("cursors") or {}
        if gw.sm.state == "INITIALIZING":
            gw.sm.start()
        self.conns[session][role].append(ws)
        self.executor_meta[id(ws)] = {
            "source": source,
            "domains": list(data.get("domains") or []),
            "session": session,
        }
        self._binds[id(ws)] = {"gw": gw, "side": role, "source": source}
        gw.connected[role] = True
        if role == "executor":
            if gw.sm.state == "RECOVERING":
                gw.sm.transition("RUNNING")  # 重连恢复（I3）
            gw.sm.executor_ready(source, cursors.get(source, 0))
        await ws.send(json.dumps({
            "type": "hello", "session": gw.session_id,
            "cursors": gw.session.cursors()}))
        # 补发缓冲（精确恢复）；多 Bot 时按域过滤
        buffered = [raw for raw in gw.outbound.get(role, [])
                    if cursors.get(raw.get("source"), 0) < raw.get("seq", 0)]
        multi_exec = len(self.conns[session]["executor"]) > 1
        for raw in buffered:
            if role == "executor" and multi_exec \
                    and ws not in self._targets_for_action(raw, session):
                continue
            await ws.send(json.dumps(raw, ensure_ascii=False))
        return self._binds[id(ws)]

    # --- 出站 -----------------------------------------------------------------
    def _targets_for_action(self, raw: dict, gsid: str) -> list:
        """§10.3 域路由：按 Registry.executor_domain 选目标连接。

        匹配顺序：声明了该域的 executor → 未声明域的 executor（通配）→ 全部。
        """
        conns = list(self.conns[gsid]["executor"])
        if len(conns) <= 1:
            return conns
        name = (raw.get("payload") or {}).get("name", "")
        entry = self.gateways[gsid].registry.get(name)
        domain = entry.executor_domain if entry else None
        if domain in (None, "", "any"):
            return conns

        def domains_of(ws) -> set:
            meta = self.executor_meta.get(id(ws), {})
            if meta.get("session") != gsid:
                return set()
            return set(meta.get("domains", []))

        exact = [ws for ws in conns if domain in domains_of(ws)]
        if exact:
            return exact
        wildcard = [ws for ws in conns if not domains_of(ws)]
        return wildcard or conns

    async def _pump(self, gsid: str, side: str) -> None:
        q = self._queues[gsid][side]
        while True:
            raw = await q.get()
            frame = json.dumps(raw, ensure_ascii=False)
            targets = (self._targets_for_action(raw, gsid) if side == "executor"
                       else list(self.conns[gsid]["agent"]))
            dead = []
            for ws in targets:
                try:
                    await ws.send(frame)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                bucket = self.conns[gsid][side]
                if ws in bucket:
                    bucket.remove(ws)
                self.executor_meta.pop(id(ws), None)


def generate_dev_certs(directory: str | Path, *,
                       cn: str = "localhost", days: int = 30) -> tuple:
    """生成自签名开发证书（依赖系统 openssl CLI）。

    返回 (cert_path, key_path)。仅用于开发/测试；
    生产环境使用受信 CA 签发证书（§12.1 第一层）。
    """
    import subprocess
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    cert, key = d / "cert.pem", d / "key.pem"
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(key), "-out", str(cert),
        "-days", str(days), "-nodes",
        "-subj", f"/CN={cn}",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"openssl failed: {out.stderr.strip()[:200]}")
    os.chmod(key, 0o600)
    return cert, key


def server_ssl_context(cert_path: str | Path, key_path: str | Path) -> "ssl.SSLContext":
    """服务端 TLS 上下文（加载 PEM 证书与私钥）。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_path), str(key_path))
    return ctx


def client_ssl_context_insecure() -> "ssl.SSLContext":
    """客户端 TLS 上下文：跳过自签名证书校验（仅测试用）。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx