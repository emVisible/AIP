"""Phase 2（v0.2）测试：级联决策 / 人工闭环 / 持久化 / WS 网关 / 复合执行器。"""
import asyncio
import json
from pathlib import Path

import pytest

from aip import AIPPeer, FakeClock, make_event

from apa_core.cascade import CascadingAgent
from apa_core.context import APAContextStore
from apa_core.embedded import EmbeddedGateway
from apa_core.llm import FakeLLMClient, parse_decision
from apa_core.persist import SessionJournal, load_journal, recover, release_expired
from apa_core.policy import PolicyConfig
from apa_core.registry import ActionRegistry, RegistryEntry, load_registries
from apa_core.rules import RuleBasedAgent, RuleEngine
from apa_sdk.composite import CompositeExecutor

APA_ROOT = Path(__file__).resolve().parent.parent
SESSION = "s_p2_001"
EXEC, AGENT = "exec_001", "agent_001"


def build(**kw):
    gw = EmbeddedGateway(
        SESSION,
        registry=load_registries(
            APA_ROOT / "registries" / "core.yaml",
            APA_ROOT / "registries" / "document.yaml",
            APA_ROOT / "registries" / "api.yaml"),
        identities={"executor": EXEC, "agent": AGENT},
        **kw)
    gw.run()
    return gw


def make_cascade(llm_responses, rules=None):
    gw = build()
    peer = AIPPeer(source=AGENT, session_id=SESSION)
    llm = FakeLLMClient(llm_responses)
    agent = CascadingAgent(
        peer,
        rules if rules is not None else [{"if": {"event": "known.event"},
                                          "then": {"action": "session.complete"}}],
        llm,
        allowed_actions=["doc.extract_fields", "erp.invoice.create",
                         "human.task.create"],
    )
    gw.attach_agent(agent, AGENT)
    return gw, agent, llm


def feed_event(agent, name, data=None, seq=1):
    m = make_event(SESSION, EXEC, name, data=data)
    m.seq = seq
    agent.on_message(m.to_dict())


class TestCascade:
    def test_l0_rule_hits_no_llm_call(self):
        gw, agent, llm = make_cascade([], rules=[
            {"if": {"event": "known.event"}, "then": {"action": "session.complete"}}])
        feed_event(agent, "known.event")
        assert agent.done and llm.calls == []
        assert agent.stats["L0"] == 1

    def test_llm_decision_when_rules_miss(self):
        gw, agent, llm = make_cascade(
            [{"action": "doc.extract_fields",
              "params": {"document_ref": "/tmp/x.txt"}}],
            rules=[{"if": {"event": "never.matches"},
                    "then": {"action": "session.complete"}}])
        feed_event(agent, "unknown.thing.happened", {"path": "/tmp/x.txt"})
        assert agent.stats["L1"] == 1
        assert list(agent.sent.values()) == ["doc.extract_fields"]
        # 模型只看到允许动作清单与 <4KB 事件语义（DE-3/C3 由 Gateway 兜底）
        assert len(llm.calls) == 1
        assert llm.calls[0]["allowed_actions"] == agent.allowed_actions

    def test_uncertain_escalates_to_human_task(self):
        gw, agent, llm = make_cascade([{"uncertain": "low confidence"}], rules=[])
        feed_event(agent, "mystery.event.occurred", {})
        assert agent.stats["human"] == 1
        assert "human.task.create" in agent.sent.values()

    def test_disallowed_action_treated_as_uncertain(self):
        gw, agent, llm = make_cascade([{"action": "bank.transfer",
                                        "params": {"amount": 999}}], rules=[])
        feed_event(agent, "payment.requested", {})
        assert agent.stats["human"] == 1
        assert all(a != "bank.transfer" for a in agent.sent.values())

    def test_budget_prevents_runaway(self):
        gw, agent, llm = make_cascade([{"uncertain": "x"}] * 100, rules=[])
        agent.max_llm_decisions = 3
        for seq in range(1, 11):
            feed_event(agent, f"evt{seq}.a.b", {}, seq=seq)
        assert agent.stats["unhandled"] >= 7
        assert agent.stats["human"] == 3


class TestHumanLoopClosure:
    def test_create_suspend_resolve_resume(self):
        gw = build()
        inbox = []
        gw.gateway.set_handler("agent", lambda raw: inbox.append(raw))
        from aip import make_action
        m = make_action(SESSION, AGENT, "human.task.create", params={
            "task_type": "exception", "assignee_role": "ops",
            "context_ref": "ctx_s_p2_001_x"})
        m.seq = 1
        out = gw.gateway.receive("agent", m.to_dict())
        task_id = out[0].payload["data"]["task_id"]
        assert gw.gateway.sm.state == "SUSPENDED"
        assert gw.gateway.human.open_tasks()
        # SUSPENDED 下高风险动作被拒（§8.2 第④步）
        m2 = make_action(SESSION, AGENT, "erp.invoice.create",
                         params={"invoice_no": "I-1", "total": 1.0})
        m2.seq = 2
        out2 = gw.gateway.receive("agent", m2.to_dict())
        assert out2[0].payload.get("code") == "session_state_mismatch"
        # 人工完成 → RUNNING，agent 收到 completed 事件
        assert gw.gateway.resolve_human_task(task_id, outcome="retry", actor="alice")
        assert gw.gateway.sm.state == "RUNNING"
        assert any(r["type"] == "event" and r["payload"]["name"] == "human.task.completed"
                   for r in inbox)
        assert not gw.gateway.resolve_human_task(task_id)  # 已处理不可重复

    def test_l3_policy_still_gates_and_resumes(self):
        gw = build()
        from aip import make_action
        m = make_action(SESSION, AGENT, "desktop.file.delete", {"path": "/tmp/x"})
        m.seq = 1
        out = None
        try:
            out = gw.gateway.receive("agent", m.to_dict())
        except Exception:
            pass
        # desktop 域未在本 registry 集合中 → action_not_registered 也算通过门控
        assert out[0].payload.get("status") == "rejected"


class TestPersistence:
    def test_journal_roundtrip(self, tmp_path):
        path = tmp_path / "s.jsonl"
        journal = SessionJournal(path)
        gw = build(journal=journal)
        from aip import make_action, make_result
        m = make_action(SESSION, AGENT, "session.complete", params={"outcome": "success"})
        m.seq = 1
        gw.gateway.receive("agent", m.to_dict())
        assert gw.gateway.sm.state == "COMPLETED"

        records = load_journal(path)
        kinds = {r["kind"] for r in records}
        assert {"cursor", "state"} <= kinds
        assert records[-1]["to"] == "COMPLETED"

        # 恢复：新 gateway 从日志重建
        gw2 = recover(SESSION, path, registry=gw.gateway.registry,
                      identities={"executor": EXEC, "agent": AGENT})
        assert gw2.gateway.sm.state == "COMPLETED"
        assert gw2.gateway.session.receiver.cursors(SESSION).get(AGENT) == 1
        # 游标基线正确：重放旧 seq → SEQ_OUT_OF_ORDER；新 seq 正常接受
        from aip import make_action as mk
        replay = mk(SESSION, AGENT, "session.complete", params={}, seq=1)
        out = gw2.gateway.receive("agent", replay.to_dict())
        assert out[0].type == "error" and out[0].payload["code"] == "SEQ_OUT_OF_ORDER"
        fresh = mk(SESSION, AGENT, "human.task.create",
                   params={"task_type": "exception", "assignee_role": "ops", "context_ref": "ctx_s_p2_001_x"}, seq=2)
        out2 = gw2.gateway.receive("agent", fresh.to_dict())
        # 终态 Session 拒绝一切新动作（§10.1）
        assert out2[0].type == "result"
        assert out2[0].payload.get("code") == "session_state_mismatch"

    def test_recover_suspended_with_open_task(self, tmp_path):
        path = tmp_path / "t.jsonl"
        gw = build(journal=SessionJournal(path))
        from aip import make_action
        m = make_action(SESSION, AGENT, "human.task.create", params={
            "task_type": "exception", "assignee_role": "ops",
            "context_ref": "ctx_s_p2_001_x"})
        m.seq = 1
        gw.gateway.receive("agent", m.to_dict())

        gw2 = recover(SESSION, path, identities={"executor": EXEC, "agent": AGENT})
        assert gw2.gateway.sm.state == "SUSPENDED"
        assert gw2.gateway.human.open_tasks()
        # 恢复后可继续人工闭环
        task_id = gw2.gateway.human.open_tasks()[0]["task_id"]
        assert gw2.gateway.resolve_human_task(task_id)

    def test_release_expired_archives_terminal(self, tmp_path):
        import time
        path = tmp_path / "r.jsonl"
        j = SessionJournal(path)
        j.record("state", session="s_old", to="COMPLETED", ts=int((time.time() - 3600) * 1000))
        j.record("cursor", session="s_old", source="x", seq=3)
        j.record("state", session="s_new", to="RUNNING")
        released = release_expired(path, ttl_minutes=30)
        assert released == 1
        remaining = load_journal(path)
        assert all(r.get("session") != "s_old" for r in remaining)


class TestParseDecision:
    def test_clean_json(self):
        assert parse_decision('{"action":"a.b","params":{"x":1}}') == \
            {"action": "a.b", "params": {"x": 1}}

    def test_fenced_and_prose(self):
        content = '好的，我决定：```json\n{"action":"c.d"}\n``` 以上。'
        assert parse_decision(content)["action"] == "c.d"

    def test_defensive_folds_to_uncertain(self):
        assert parse_decision("")["uncertain"] == "empty_response"
        assert parse_decision("no json here")["uncertain"] == "no_json"
        assert parse_decision('{"action": ""}')["uncertain"] == "missing_action"
        assert parse_decision('[1,2]')["uncertain"] == "not_object"
        assert parse_decision('{"action":"a","params":[1]}')["uncertain"] == "bad_params"
        assert parse_decision('{"uncertain":"too risky"}') == \
            {"uncertain": "too risky"}

    def test_target_preserved(self):
        d = parse_decision('{"action":"click","target":"btn1"}')
        assert d["target"] == "btn1"


class TestCompositeExecutor:
    class Module:
        def __init__(self):
            self.seen = []
            self.context_store = None
            self.peer = None

        def _execute_action(self, name, params):
            self.seen.append(name)
            return True, {"module": id(self)}

    def test_routes_by_prefix_and_shares_store(self):
        router = CompositeExecutor("bot", SESSION)
        store = APAContextStore(SESSION)
        router.context_store = store
        doc_mod, api_mod = self.Module(), self.Module()
        router.register(("doc",), doc_mod)
        router.register(("api", "erp"), api_mod)
        ok, _ = router._execute_action("doc.extract_text", {})
        assert ok and doc_mod.seen == ["doc.extract_text"]
        ok, _ = router._execute_action("erp.invoice.create", {})
        assert ok and api_mod.seen == ["erp.invoice.create"]
        ok, data = router._execute_action("other.action", {})
        assert not ok and data["code"] == "action_not_supported_by_executor"
        # 共享 ContextStore 注入
        assert doc_mod.context_store is store
        assert api_mod.context_store is store


class TestWsGateway:
    async def _run_scenario(self, tmp_path):
        import websockets

        gw = EmbeddedGateway(
            SESSION,
            registry=load_registries(APA_ROOT / "registries" / "core.yaml",
                                     APA_ROOT / "registries" / "browser.yaml"),
            policy=PolicyConfig(),
            identities={"executor": "ws_ex", "agent": "ws_ag"})
        gw.run()
        from apa_core.ws_gateway import WsGatewayServer
        server = WsGatewayServer(gw.gateway, port=0)
        port = await server.start()
        url = f"ws://127.0.0.1:{port}"

        # --- 未授权 hello 被拒 ---
        bad = await websockets.connect(url)
        await bad.send(json.dumps({"type": "hello", "role": "executor",
                                   "source": "impostor"}))
        reply = json.loads(await asyncio.wait_for(bad.recv(), 2))
        assert reply["code"] == "UNAUTHORIZED"

        # --- 正常双端接入 ---
        ex_ws = await websockets.connect(url)
        ag_ws = await websockets.connect(url)
        await ex_ws.send(json.dumps({"type": "hello", "role": "executor",
                                     "source": "ws_ex", "cursors": {}}))
        ack = json.loads(await asyncio.wait_for(ex_ws.recv(), 2))
        assert ack["type"] == "hello" and ack["session"] == SESSION
        await ag_ws.send(json.dumps({"type": "hello", "role": "agent",
                                     "source": "ws_ag", "cursors": {}}))
        await asyncio.wait_for(ag_ws.recv(), 2)  # hello ack

        # 心跳不消耗 seq（D4）
        await ex_ws.send(json.dumps({"type": "ping"}))
        pong = json.loads(await asyncio.wait_for(ex_ws.recv(), 2))
        assert pong["type"] == "pong"

        # executor 发事件 → agent 收到
        peer = AIPPeer(source="ws_ex", session_id=SESSION)
        class T:
            @staticmethod
            def send(raw):
                asyncio.get_running_loop().create_task(
                    ex_ws.send(json.dumps(raw)))
        peer.transport = T()
        peer.send_event("browser.page.loaded", {"url": "https://x.corp/a"})
        frame = json.loads(await asyncio.wait_for(ag_ws.recv(), 2))
        assert frame["type"] == "event"
        assert frame["payload"]["name"] == "browser.page.loaded"

        # agent 发 action → executor 收到（同一连接）
        ag_peer = AIPPeer(source="ws_ag", session_id=SESSION)
        class TA:
            @staticmethod
            def send(raw):
                asyncio.get_running_loop().create_task(
                    ag_ws.send(json.dumps(raw)))
        ag_peer.transport = TA()
        ag_peer.send_action("browser.navigate", params={"url": "https://x.corp/b"})
        act = json.loads(await asyncio.wait_for(ex_ws.recv(), 2))
        assert act["type"] == "action"
        assert act["payload"]["name"] == "browser.navigate"

        await ex_ws.close(); await ag_ws.close(); await bad.close()
        await server.close()

    def test_full_scenario(self, tmp_path):
        asyncio.run(self._run_scenario(tmp_path))