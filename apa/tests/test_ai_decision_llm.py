"""P18-M1 内置 LLM 决策贯通测试。

三层验证：
  1. ProcessEngine.ai_decision：meta 透传 + 无 decision_fn 降级
  2. make_llm_decision_fn：预算 / 异常兜底 / action 适配（FakeLLMClient）
  3. ServeApp 注入 FakeLLMClient 全链路：决策驱动条件分支 → 命中目标动作
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from apa_core.llm import FakeLLMClient
from apa_core.process import ProcessEngine, build_process
from apa_core.serve import ServeApp, make_llm_decision_fn


# ---- 1. 引擎层 ---------------------------------------------------------------

def _engine(steps, decision_fn=None):
    sent = []

    def send_fn(action, params):
        sent.append((action, params))
        return True, {"ok": True}

    proc = build_process({"process": {
        "id": "t_ai", "mode": "process",
        "trigger": {"type": "manual"}, "max_actions": 20,
        "steps": steps,
        "error_handlers": {
            "escalate": {"action": "human.escalate",
                          "params": {}}}}})
    eng = ProcessEngine(proc, send_fn, decision_fn=decision_fn)
    eng.run.scopes["event"] = {}
    return eng, sent


AI_STEP = {
    "id": "decide", "type": "ai_decision",
    "params": {"context": ["{{event.data.summary}}"],
               "available_actions": ["erp.order.approve",
                                      "erp.order.reject"]},
}


class TestEngineAiDecision:
    def test_no_fn_degrades_with_reason(self):
        eng, sent = _engine([dict(AI_STEP),
                             {"id": "esc_done", "action": "noop"}])
        # 无 handler escalate → 流程失败；但 steps 记录了 reason
        eng._run_from(0)
        entry = [s for s in eng.run.steps if s.get("type") == "ai_decision"][0]
        assert entry["outcome"] == "uncertain"
        assert entry["meta"]["_reason"] == "no_decision_fn"

    def test_action_branch_and_meta(self):
        calls = {}

        def fn(ctx_list, available):
            calls["ctx"] = ctx_list
            return {"outcome": "erp.order.approve",
                    "_level": "L2", "_ms": 12.5}

        eng, sent = _engine([
            dict(AI_STEP),
            {"id": "branch",
             "action": "mark.approved",
             "condition": "steps.decide.outcome == 'erp.order.approve'"},
        ], decision_fn=fn)
        eng.run.scopes["event"] = {"data": {"summary": "小额"}}
        eng._run_from(0)

        assert eng.run.outcome == "success"
        assert ("mark.approved", {}) in sent      # 条件分支命中
        entry = [s for s in eng.run.steps
                 if s.get("type") == "ai_decision"][0]
        assert entry["meta"]["_level"] == "L2"
        assert entry["meta"]["_ms"] == 12.5
        assert calls["ctx"] == ["小额"]           # context 模板已解析

    def test_uncertain_routes_escalate_handler(self):
        def fn(ctx_list, available):
            return {"outcome": "uncertain", "_reason": "low_conf"}

        eng, sent = _engine([dict(AI_STEP)], decision_fn=fn)
        from apa_core.process import StepDef

        eng.proc.error_handlers["escalate"] = StepDef(
            id="escalate", action="human.notify")
        eng._run_from(0)
        assert any(s.get("step") == "escalate(handler)"
                   for s in eng.run.steps)


# ---- 2. 工厂层 ---------------------------------------------------------------

class TestMakeLlmDecisionFn:
    def test_action_adapter(self):
        fake = FakeLLMClient([{"action": "a.b", "params": {"k": 1}}])
        d = make_llm_decision_fn(fake, max_decisions=5)
        out = d(["ctx"], ["a.b"])
        assert out["outcome"] == "a.b" and out["params"] == {"k": 1}
        assert out["_budget_used"] == 1

    def test_uncertain_passthrough_reason(self):
        fake = FakeLLMClient([{"uncertain": "低置信度"}])
        out = make_llm_decision_fn(fake)([], [])
        assert out["outcome"] == "uncertain"
        assert out["_reason"] == "低置信度"

    def test_budget_exhausted(self):
        class Endless:
            def decide(self, **kw):
                return {"action": "x"}

        d = make_llm_decision_fn(Endless(), max_decisions=2)
        assert d([], ["x"])["outcome"] == "x"
        assert d([], ["x"])["outcome"] == "x"
        third = d([], ["x"])
        assert third["outcome"] == "uncertain"
        assert third["_reason"] == "budget_exhausted"   # 工厂层拦截
        assert third["_budget_used"] == 2

    def test_llm_exception_becomes_uncertain(self):
        class Boom:
            def decide(self, **kw):
                raise RuntimeError("net down")

        out = make_llm_decision_fn(Boom())(["c"], ["a"])
        assert out["outcome"] == "uncertain"
        assert "RuntimeError" in out["_reason"]


# ---- 3. ServeApp 注入全链路 ----------------------------------------------------

@pytest.fixture()
def target_stub():
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n) or b"{}"
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = {}
            hits.append({"path": self.path, "body": parsed})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            body = b'{"ok":true}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1], hits
    srv.shutdown()


def test_serve_ai_decision_drives_branch(tmp_path, target_stub,
                                         monkeypatch):
    """serve 会话中 ai_decision 真实调用注入的 FakeLLM 并驱动分支。"""
    port_notify, hits = target_stub
    monkeypatch.delenv("APA_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    procs = tmp_path / "procs"
    procs.mkdir()
    (procs / "ai_flow.yaml").write_text(
        "process:\n"
        "  id: ai_flow\n"
        "  mode: process\n"
        "  trigger: {type: event, name: ai.ticket}\n"
        "  error_handlers:\n"
        "    escalate: {action: api.http.post, params: "
        "{url: 'http://127.0.0.1:%d/esc'}}\n"
        "  steps:\n"
        "    - id: decide\n"
        "      type: ai_decision\n"
        "      params:\n"
        "        context: ['{{event.data.summary}}']\n"
        "        available_actions: [api.http.post]\n"
        "    - id: act\n"
        "      condition: \"steps.decide.outcome == 'api.http.post'\"\n"
        "      action: api.http.post\n"
        "      params: {url: 'http://127.0.0.1:%d/act'}\n"
        % (port_notify, port_notify),
        encoding="utf-8")

    fake = FakeLLMClient([{"action": "api.http.post"}])
    # 环境快照：防止 .env 加载污染全局 os.environ（跨测试泄漏）
    import os as _os

    saved_env = {k: _os.environ.get(k)
                 for k in ("APA_LLM_API_KEY", "DEEPSEEK_API_KEY",
                           "APA_LLM_MODEL", "DEEPSEEK_MODEL")}
    app = ServeApp(
        journals=[str(tmp_path / "*.jsonl")],
        port=0,
        ws_port=None,
        processes_dir=str(procs),
        registry=__import__("apa_core.registry", fromlist=["x"])
        .load_registries(str(APA_DIR_HOLDER[0] / "registries" / "core.yaml"),
                         str(APA_DIR_HOLDER[0] / "registries" / "api.yaml")),
        mock_erp=False,
        runs_dir=str(tmp_path / "runs"),
        tick_interval_s=0.2, session_timeout_s=15.0,
        llm_client=fake,
    )
    app.add_process_job("ai_job", kind="event",
                        process="ai_flow", event="ai.ticket")
    app.studio_start_background()

    r = app.dispatch_external_event("ai.ticket",
                                    {"summary": "发票金额异常"})
    deadline = time.time() + 12
    while time.time() < deadline and not hits:
        time.sleep(0.05)

    assert r["dispatched"] == 1
    assert any(h["path"].endswith("/act") for h in hits), \
        f"分支未命中 /act: {hits}"
    assert not any(h["path"].endswith("/esc") for h in hits), \
        "不应走升级分支"
    assert fake.calls, "FakeLLM 从未被调用"
    kw = fake.calls[0]
    assert kw["event_name"] == "ai_decision"
    assert "发票金额异常" in json.dumps(kw["event_data"], ensure_ascii=False)
    app.shutdown()
    for k, v in saved_env.items():
        if v is None:
            _os.environ.pop(k, None)
        else:
            _os.environ[k] = v


APA_DIR_HOLDER = [__import__("pathlib").Path(__file__).resolve().parents[1]]