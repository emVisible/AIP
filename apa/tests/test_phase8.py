"""Phase 7（生产加固）测试：TLS / 令牌认证 / SqliteJournal / 多会话池 / 延迟基准。"""
import asyncio
import json
import time
from pathlib import Path

import pytest

from aip import FakeClock, make_action, make_event

from apa_core.embedded import EmbeddedGateway
from apa_core.policy import PolicyConfig
from apa_core.registry import load_registries

APA_ROOT = Path(__file__).resolve().parent.parent
SESSION = "s_p8_001"


def registries():
    return load_registries(APA_ROOT / "registries" / "core.yaml",
                           APA_ROOT / "registries" / "browser.yaml")


def build(session=SESSION, **kw):
    gw = EmbeddedGateway(session, registry=registries(),
                         identities={"executor": f"ex_{session}",
                                     "agent": f"ag_{session}"}, **kw)
    gw.run()
    return gw


# --- TLS + 令牌认证 --------------------------------------------------------------
class TestTlsAndToken:
    def test_wss_handshake_and_loop_with_token(self, tmp_path):
        asyncio_run(self._scenario(tmp_path))

    async def _scenario(self, tmp_path):
        import websockets

        from apa_core.ws_gateway import (
            WsGatewayServer,
            client_ssl_context_insecure,
            generate_dev_certs,
            server_ssl_context,
        )

        cert, key = generate_dev_certs(tmp_path / "certs")
        gw = build()
        server = WsGatewayServer(
            gw.gateway, port=0,
            ssl_context=server_ssl_context(cert, key),
            hello_token="ops-secret-1",
        )
        port = await server.start()
        url = f"wss://127.0.0.1:{port}"
        insecure = client_ssl_context_insecure()

        # 缺 token → UNAUTHORIZED（TLS 已握手成功才能收到应用层错误）
        bad = await websockets.connect(url, ssl=insecure)
        await bad.send(json.dumps({"type": "hello", "role": "agent",
                                   "source": f"ag_{SESSION}", "session": SESSION}))
        reply = json.loads(await asyncio.wait_for(bad.recv(), 3))
        assert reply["code"] == "UNAUTHORIZED"
        assert "token" in reply["message"]

        # 错 token → UNAUTHORIZED
        wrong = await websockets.connect(url, ssl=insecure)
        await wrong.send(json.dumps({"type": "hello", "role": "agent",
                                     "source": f"ag_{SESSION}",
                                     "session": SESSION, "token": "nope"}))
        reply = json.loads(await asyncio.wait_for(wrong.recv(), 3))
        assert reply["code"] == "UNAUTHORIZED"

        # 正确 token → ack；事件经 wss 到达
        ok = await websockets.connect(url, ssl=insecure)
        await ok.send(json.dumps({"type": "hello", "role": "agent",
                                  "source": f"ag_{SESSION}",
                                  "session": SESSION, "token": "ops-secret-1"}))
        ack = json.loads(await asyncio.wait_for(ok.recv(), 3))
        assert ack["type"] == "hello" and ack["session"] == SESSION

        ev = make_event(SESSION, f"ex_{SESSION}", "browser.page.loaded",
                        {"url": "https://x"})
        ev.seq = 1
        gw.gateway.deliver("executor", ev.to_dict())
        frame = json.loads(await asyncio.wait_for(ok.recv(), 3))
        assert frame["payload"]["name"] == "browser.page.loaded"

        await bad.close(); await wrong.close(); await ok.close()
        await server.close()


def asyncio_run(coro):
    import asyncio
    asyncio.run(coro)


# --- SqliteJournal ----------------------------------------------------------------
class TestSqliteJournal:
    def test_roundtrip_and_recover_compat(self, tmp_path):
        from apa_core.persist import (
            SessionJournal,
            SqliteJournal,
            journal_records,
            recover,
        )

        jpath = tmp_path / "s.sqlite"
        jobj = SqliteJournal(jpath)
        gw = EmbeddedGateway(SESSION, registry=registries(),
                             identities={"executor": "ex", "agent": "ag"},
                             journal=jobj)
        gw.run()
        m = make_action(SESSION, "ag", "human.task.create",
                        params={"task_type": "approval", "assignee_role": "ops",
                                "context_ref": f"ctx_{SESSION}_i"})
        m.seq = 1
        gw.gateway.receive("agent", m.to_dict())
        assert gw.gateway.sm.state == "SUSPENDED"

        # 统一读取层
        records = journal_records(jobj)
        assert records[-1]["kind"] == "task"

        # recover 接受 sqlite 路径
        gw2 = recover(SESSION, jpath, identities={"executor": "ex", "agent": "ag"})
        assert gw2.gateway.sm.state == "SUSPENDED"
        task_id = gw2.gateway.human.open_tasks()[0]["task_id"]
        assert gw2.gateway.resolve_human_task(task_id, outcome="approve")
        assert gw2.gateway.sm.state == "RUNNING"
        # 追加写回到同一个 sqlite
        kinds = [r["kind"] for r in journal_records(jpath)]
        assert kinds.count("state") >= 4  # 原 RUNNING/SUSPENDED + 恢复期追加

    def test_mixed_backends_isolated(self, tmp_path):
        from apa_core.persist import open_journal

        a = open_journal(tmp_path / "a.jsonl")
        b = open_journal(tmp_path / "b.sqlite")
        assert type(a).__name__ == "SessionJournal"
        assert type(b).__name__ == "SqliteJournal"
        b.record("cursor", session="sb", source="x", seq=9)
        assert a.all() == [] or all(r.get("session") != "sb" for r in a.all())


# --- 多会话池 ------------------------------------------------------------------------
class TestMultiSessionPool:
    def test_two_sessions_isolated_on_one_server(self, tmp_path):
        asyncio_run(self._scenario())

    async def _scenario(self):
        import websockets

        from apa_core.ws_gateway import WsGatewayServer

        gwA = EmbeddedGateway("sess_A", registry=registries(),
                              identities={"executor": "ex_A", "agent": "ag_A"})
        gwB = EmbeddedGateway("sess_B", registry=registries(),
                              identities={"executor": "ex_B", "agent": "ag_B"})
        gwA.run(); gwB.run()

        seenA, seenB, execB = [], [], []
        inner_a = None

        server = WsGatewayServer(gateways={"sess_A": gwA.gateway,
                                           "sess_B": gwB.gateway}, port=0)
        port = await server.start()
        url = f"ws://127.0.0.1:{port}"

        async def connect_agent(sid: str, src: str):
            ws = await websockets.connect(url)
            await ws.send(json.dumps({"type": "hello", "role": "agent",
                                      "source": src, "session": sid}))
            await asyncio.wait_for(ws.recv(), 3)   # hello ack
            return ws

        agA = await connect_agent("sess_A", "ag_A")
        agB = await connect_agent("sess_B", "ag_B")

        # 会话 A 的事件 → 只到 A 的 agent
        evA = make_event("sess_A", "ex_A", "browser.page.loaded",
                         {"url": "https://a.corp"})
        evA.seq = 1
        gwA.gateway.deliver("executor", evA.to_dict())
        frame = json.loads(await asyncio.wait_for(agA.recv(), 3))
        assert frame["payload"]["data"]["url"].startswith("https://a")

        # B 的 agent 不应收到 A 的任何消息
        try:
            await asyncio.wait_for(agB.recv(), 0.5)
            isolated = False
        except asyncio.TimeoutError:
            isolated = True
        assert isolated

        # 未知 session → 明确错误
        ghost = await websockets.connect(url)
        await ghost.send(json.dumps({"type": "hello", "role": "agent",
                                     "source": "ag_ghost",
                                     "session": "sess_GHOST"}))
        reply = json.loads(await asyncio.wait_for(ghost.recv(), 3))
        assert reply["code"] == "INVALID_MESSAGE"
        assert "unknown session" in reply["message"]

        await agA.close(); await agB.close(); await ghost.close()
        await server.close()


# --- 延迟基准（§14.4） ----------------------------------------------------------------
class TestLatencyBenchmark:
    def test_smoke_percentiles(self):
        from benchmarks.latency import run as latency_run

        data = latency_run(n_actions=50)
        assert data["n"] == 50
        assert data["p50_ms"] >= 0 and data["p95_ms"] >= data["p50_ms"]
        assert data["actions_per_sec"] > 10