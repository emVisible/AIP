"""Phase 3（v0.3）测试：Process Mode / Desktop / Studio / WS 多 Bot / 补漏项。"""
import asyncio
import json
import time
from pathlib import Path

import pytest

from aip import FakeClock, AIPPeer, make_action, make_event, make_result

from apa_core.embedded import EmbeddedGateway
from apa_core.persist import SessionJournal
from apa_core.policy import PolicyConfig
from apa_core.process import (
    ProcessDefinitionError,
    ProcessEngine,
    build_process,
    eval_condition,
    load_process,
)
from apa_core.registry import load_registries

APA_ROOT = Path(__file__).resolve().parent.parent
SESSION = "s_p3_001"
EXEC, AGENT = "bot_01", "proc_01"


def all_registries():
    return load_registries(
        APA_ROOT / "registries" / "core.yaml",
        APA_ROOT / "registries" / "browser.yaml",
        APA_ROOT / "registries" / "desktop.yaml",
        APA_ROOT / "registries" / "document.yaml",
        APA_ROOT / "registries" / "api.yaml")


class TestProcessEngine:
    def make_engine(self, tmp_path, steps_yaml: str, log=None):
        proc_file = tmp_path / "p.yaml"
        proc_file.write_text(steps_yaml, encoding="utf-8")
        proc = load_process(str(proc_file))
        sent = []

        def send_fn(name, params):
            if log is not None:
                log.append((name, params))
            if name == "context.get":
                # 模拟执行器回包（CoD 解包装）
                return True, {"ref": params["ref"],
                              "data": {"order_id": "PO-1", "amount": 45000}}
            return True, {"echo": params}

        engine = ProcessEngine(proc, send_fn)
        return engine, sent, send_fn

    def test_c3_forbidden_in_steps(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("""
process:
  id: x
  steps:
    - id: a
      action: y.z
      idempotency: required
""", encoding="utf-8")
        with pytest.raises(ProcessDefinitionError):
            load_process(str(bad))

    def test_template_and_cod_unwrap(self, tmp_path):
        log = []
        yaml_text = """
process:
  id: p1
  trigger: { name: e.a.b }
  steps:
    - id: fetch
      action: context.get
      params: { ref: "{{ event.data.ref }}" }
      output_as: order
    - id: act
      action: erp.order.approve
      params: { order_id: "{{ steps.order.order_id }}" }
"""
        engine, _, send_fn = self.make_engine(tmp_path, yaml_text, log)
        engine.on_trigger("e.a.b", {"ref": "ctx_s_p3_001_o"})
        assert ("context.get", {"ref": "ctx_s_p3_001_o"}) == log[0]
        assert log[1][1]["order_id"] == "PO-1"  # CoD 解包 + 整值模板
        assert engine.run.done and engine.run.outcome == "success"

    def test_condition_branching(self, tmp_path):
        yaml_text = """
process:
  id: p2
  trigger: { name: e.a.b }
  steps:
    - id: fetch
      action: context.get
      params: { ref: r }
      output_as: order
    - id: approve
      condition: "{{ steps.order.amount < 100000 }}"
      action: erp.order.approve
      params: {}
    - id: reject
      condition: "{{ steps.order.amount >= 100000 }}"
      action: erp.order.reject
      params: {}
"""
        log = []
        engine, _, _ = self.make_engine(tmp_path, yaml_text, log)
        engine.on_trigger("e.a.b", {"ref": "r"})
        actions = [n for n, _ in log]
        assert "erp.order.approve" in actions and "erp.order.reject" not in actions

    def test_failure_goto_handler_suspends_via_task(self, tmp_path):
        yaml_text = """
process:
  id: p3
  trigger: { name: e.a.b }
  steps:
    - id: boom
      action: always.fails
      params: {}
      on_failure: { goto: escalate }
  error_handlers:
    escalate:
      action: human.task.create
      params: { task_type: exception, assignee_role: ops,
                context_ref: ctx_s_p3_001_x }
"""
        calls = []

        def send_fn(name, params):
            calls.append(name)
            if name == "always.fails":
                return False, {"code": "kaput"}
            return True, {}

        engine = ProcessEngine(load_process(str(tmp_path / "p.yaml")) if False else
                               build_process(_yaml(yaml_text)), send_fn)
        engine.on_trigger("e.a.b", {})
        assert calls == ["always.fails", "human.task.create"]
        assert engine.run.outcome == "escalated"

    def test_max_actions_guard(self, tmp_path):
        yaml_text = """
process:
  id: p4
  trigger: { name: e.a.b }
  max_actions: 2
  steps:
    - id: s1
      action: a.one
      params: {}
    - id: s2
      action: a.two
      params: {}
    - id: s3
      action: a.three
      params: {}
"""
        engine, _, _ = self.make_engine(tmp_path, yaml_text)
        engine.on_trigger("e.a.b", {})
        assert engine.run.outcome == "max_actions_exceeded"
        assert engine.run.actions_sent == 2  # 第 3 步被预算拦截

    def test_ai_decision_node(self, tmp_path):
        yaml_text = """
process:
  id: p5
  trigger: { name: e.a.b }
  steps:
    - id: decide
      type: ai_decision
      params:
        available_actions: [x.y]
    - id: act
      condition: "{{ steps.decide.outcome == 'approve' }}"
      action: x.y
      params: {}
  error_handlers:
    escalate:
      action: human.task.create
      params: {}
"""

        def send_fn(name, params):
            return True, {}

        proc = build_process(_yaml(yaml_text))
        eng_ok = ProcessEngine(proc, send_fn,
                               decision_fn=lambda ctx, acts: {"outcome": "approve"})
        eng_ok.on_trigger("e.a.b", {})
        assert eng_ok.run.outcome == "success"

        eng_uncertain = ProcessEngine(build_process(_yaml(yaml_text)), send_fn,
                                      decision_fn=lambda c, a: {"outcome": "uncertain"})
        eng_uncertain.on_trigger("e.a.b", {})
        assert eng_uncertain.run.outcome == "escalated"

    def test_unsafe_condition_rejected(self):
        for expr in ("__import__('os').system('id')",
                     "().__class__.__bases__",
                     "[x for x in ()]"):
            with pytest.raises(ProcessDefinitionError):
                eval_condition(expr, {})


def _yaml(text: str) -> dict:
    import yaml as _yaml_mod
    return _yaml_mod.safe_load(text)


class TestGapFixes:
    def test_abort_marks_pending_timeout_and_cancels(self):
        gw = EmbeddedGateway(SESSION, registry=all_registries(),
                             identities={"executor": EXEC, "agent": AGENT})
        gw.run()
        m = make_action(SESSION, AGENT, "browser.navigate", params={"url": "https://x"})
        m.seq = 1
        out = gw.gateway.receive("agent", m.to_dict())
        assert gw.gateway.pending
        assert gw.gateway.abort(reason="ops_kill")
        status, _ = gw.gateway.session.actions.outcome(out[0].id)
        assert status == "timeout"
        assert gw.gateway.sm.state == "CANCELLED"
        assert not gw.gateway.abort()  # 终态不可再终止

    def test_expect_tracking(self):
        gw = EmbeddedGateway(SESSION, registry=all_registries(),
                             identities={"executor": EXEC, "agent": AGENT})
        gw.run()
        m = make_action(SESSION, AGENT, "browser.navigate", params={"url": "https://x"})
        m.seq = 1
        out = gw.gateway.receive("agent", m.to_dict())
        assert gw.gateway.unsatisfied_expects() == {out[0].id: "browser.page.loaded"}
        ev = make_event(SESSION, EXEC, "browser.page.loaded", {})
        ev.seq = 1
        gw.gateway.receive("executor", ev.to_dict())
        assert gw.gateway.unsatisfied_expects() == {}
        assert gw.gateway.satisfied_expects == 1

    def test_session_ttl_idle_expiry(self):
        clock = FakeClock(start_ms=1000)
        gw = EmbeddedGateway(SESSION, registry=all_registries(),
                             identities={"executor": EXEC, "agent": AGENT},
                             clock=clock, session_ttl_ms=5000)
        gw.run()
        m = make_action(SESSION, AGENT, "session.complete", params={"outcome": "success"})
        m.seq = 1
        out = gw.gateway.receive("agent", m.to_dict())  # 活动时间戳=1000
        clock.advance(6000)  # 空闲超 TTL
        m2 = make_action(SESSION, AGENT, "session.complete", params={"outcome": "success"})
        m2.seq = 2
        out2 = gw.gateway.receive("agent", m2.to_dict())
        assert out2[0].type == "error"
        assert out2[0].payload["code"] == "SESSION_EXPIRED"

    def test_multi_executor_identity_membership(self):
        gw = EmbeddedGateway(SESSION, registry=all_registries(),
                             identities={"executor": ["bot_a", "bot_b"],
                                         "agent": AGENT})
        gw.run()
        ok_msg = make_event(SESSION, "bot_b", "browser.page.loaded", {})
        ok_msg.seq = 1
        out = gw.gateway.receive("executor", ok_msg.to_dict())
        assert out[0].type == "event"
        bad = make_event(SESSION, "bot_x", "browser.page.loaded", {})
        bad.seq = 1
        out2 = gw.gateway.receive("executor", bad.to_dict())
        assert out2[0].payload["code"] == "UNAUTHORIZED"


class TestDesktopExecutor:
    def test_mock_backend_actions(self):
        from apa_executors.desktop_executor import DesktopExecutor, MockDesktopBackend
        ex = DesktopExecutor(EXEC, SESSION, backend=MockDesktopBackend())
        ok, _ = ex._execute_action("desktop.window.activate",
                                   {"app_name": "ERP客户端", "title": ""})
        assert ok
        ok, data = ex._execute_action("desktop.element.click",
                                      {"element_id": "btn-approve"})
        assert ok and data["clicked"]["text"] == "批准"
        ok, _ = ex._execute_action("desktop.keyboard.input", {"text": "hello"})
        assert ok and ex.backend.typed == ["hello"]
        ok, data = ex._execute_action("desktop.window.close",
                                      {"app_name": "ERP客户端", "title": "采购订单 - 待审批"})
        assert ok and ex.backend.closed

    def test_observe_emits_window_events_once(self):
        from apa_executors.desktop_executor import DesktopExecutor, MockDesktopBackend
        events = []
        ex = DesktopExecutor(EXEC, SESSION, backend=MockDesktopBackend())
        orig_emit = ex.emit
        ex.emit = lambda name, data=None: events.append(name) or orig_emit(name, data)
        n1 = ex.observe()
        n2 = ex.observe()
        assert n1 >= 1 and n2 == 0  # 新窗口只发一次


class TestStudio:
    def test_collect_and_api(self, tmp_path):
        from apa_core.studio import StudioServer
        jpath = tmp_path / "s.jsonl"
        journal = SessionJournal(jpath)
        gw = EmbeddedGateway(SESSION, registry=all_registries(),
                             identities={"executor": EXEC, "agent": AGENT},
                             journal=journal)
        gw.run()
        m = make_action(SESSION, AGENT, "session.complete", params={"outcome": "success"})
        m.seq = 1
        gw.gateway.receive("agent", m.to_dict())

        studio = StudioServer([str(jpath)], port=0)
        sessions = studio.sessions()
        assert SESSION in sessions
        assert sessions[SESSION]["state"] == "COMPLETED"

        server = studio.start_background()
        import urllib.request
        with urllib.request.urlopen(
                f"http://127.0.0.1:{server}/api/sessions") as resp:
            data = json.loads(resp.read())
        assert SESSION in data
        with urllib.request.urlopen(f"http://127.0.0.1:{server}/") as resp:
            html = resp.read().decode()
        assert SESSION in html and "APA Studio" in html
        studio.shutdown()


@pytest.mark.e2e
class TestWsMultiBotRouting:
    def test_domain_routing(self, tmp_path):
        asyncio.run(self._scenario(tmp_path))

    async def _scenario(self, tmp_path):
        import websockets

        gw = EmbeddedGateway(
            SESSION,
            registry=all_registries(),
            policy=PolicyConfig(),
            identities={"executor": ["ws_browser", "ws_api"], "agent": "ws_ag"})
        gw.run()
        from apa_core.ws_gateway import WsGatewayServer
        server = WsGatewayServer(gw.gateway, port=0)
        port = await server.start()
        url = f"ws://127.0.0.1:{port}"

        browser_ws = await websockets.connect(url)
        api_ws = await websockets.connect(url)
        ag_ws = await websockets.connect(url)

        await browser_ws.send(json.dumps({
            "type": "hello", "role": "executor", "source": "ws_browser",
            "domains": ["browser"], "cursors": {}}))
        await asyncio.wait_for(browser_ws.recv(), 2)
        await api_ws.send(json.dumps({
            "type": "hello", "role": "executor", "source": "ws_api",
            "domains": ["api"], "cursors": {}}))
        await asyncio.wait_for(api_ws.recv(), 2)
        await ag_ws.send(json.dumps({
            "type": "hello", "role": "agent", "source": "ws_ag", "cursors": {}}))
        await asyncio.wait_for(ag_ws.recv(), 2)

        async def send_agent_action(name, params):
            peer_seq = next(_seq_counter)
            msg = make_action(SESSION, "ws_ag", name, params=params)
            msg.seq = peer_seq
            await ag_ws.send(json.dumps(msg.to_dict()))

        import itertools
        _seq_counter = itertools.count(1)

        # browser 域动作 → 只到 browser bot
        await send_agent_action("browser.navigate", {"url": "https://x"})
        frame = json.loads(await asyncio.wait_for(browser_ws.recv(), 2))
        assert frame["payload"]["name"] == "browser.navigate"
        # api 域动作 → 只到 api bot（browser 无消息）
        await send_agent_action("erp.invoice.create",
                                {"invoice_no": "I-1", "total": 5})
        frame = json.loads(await asyncio.wait_for(api_ws.recv(), 2))
        assert frame["payload"]["name"] == "erp.invoice.create"
        # agent 侧不应收到 executor 出站帧
        try:
            await asyncio.wait_for(ag_ws.recv(), 0.4)
            raised = False
        except asyncio.TimeoutError:
            raised = True
        assert raised

        for ws in (browser_ws, api_ws, ag_ws):
            await ws.close()
        await server.close()