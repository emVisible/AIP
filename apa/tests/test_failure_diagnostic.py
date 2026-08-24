"""Phase C 失败回流诊断测试：journal 解析 + LLM 解释 + API E2E。"""
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apa_core.api import create_app
from apa_core.intent.diagnose import FailureDiagnostic


class ScriptedLLM:
    def __init__(self, reply):
        self.reply = json.dumps(reply) if isinstance(reply, dict) else reply
        self.prompts = []

    def chat(self, messages):
        self.prompts.append(messages[-1]["content"])
        return self.reply


JOURNAL_LINES = [
    {"kind": "state", "to": "RUNNING", "session": "s_d1", "ts": 1},
    {"kind": "action_result", "session": "s_d1", "ts": 2,
     "source": "bot_x", "status": "failed",
     "code": "element_not_found",
     "detail": "submit-btn missing"},
    {"kind": "action_result", "session": "s_d1", "ts": 3,
     "source": "bot_x", "status": "ok"},
    {"kind": "outcome_summary", "session": "s_d1", "ts": 4,
     "outcome": "failed", "steps": 1},
]


class TestExtract:
    def test_failures_extracted(self):
        recs = [json.loads(json.dumps(r)) for r in JOURNAL_LINES]
        ctx = FailureDiagnostic.extract_failures(recs)
        assert ctx["outcome"] == "failed"
        assert ctx["failed_count"] == 1
        fa = ctx["failed_actions"][0]
        assert fa["code"] == "element_not_found"
        assert fa["status"] == "failed"

    def test_ok_results_ignored(self):
        recs = [json.loads(json.dumps(r)) for r in JOURNAL_LINES]
        ctx = FailureDiagnostic.extract_failures(recs)
        assert all(fa["status"] != "ok"
                   for fa in ctx["failed_actions"])

    def test_empty_records(self):
        ctx = FailureDiagnostic.extract_failures([])
        assert ctx["outcome"] == "unknown" and ctx["failed_count"] == 0


class TestExplain:
    def test_explanation_and_suggestion(self):
        diag = FailureDiagnostic(ScriptedLLM({
            "explanation": "点击失败：页面无 submit-btn",
            "suggestion": "先 if.element_visible 判断再点击"}))
        out = diag.explain({"outcome": "failed", "failed_actions": [
            {"action": "browser.click", "status": "failed",
             "code": "element_not_found"}]})
        assert "submit-btn" in out["explanation"]
        assert "element_visible" in out["suggestion"]

    def test_llm_failure_wrapped(self):
        class Boom:
            def chat(self, messages):
                raise RuntimeError("net down")

        out = FailureDiagnostic(Boom()).explain(
            {"outcome": "failed", "failed_actions": []})
        assert out["error"].startswith("llm_error:RuntimeError")

    def test_no_client_dependency_missing(self):
        out = FailureDiagnostic(None).explain({})
        assert out["error"] == "dependency_missing"


class TestApiE2E:
    def _app(self, tmp_path, diag):
        jf = tmp_path / "runs" / "s_diag.jsonl"
        jf.parent.mkdir(parents=True, exist_ok=True)
        jf.write_text("\n".join(
            json.dumps(r) for r in JOURNAL_LINES))
        return create_app(journals=[str(jf)],
                          runs_dir=str(tmp_path),
                          failure_diagnostic=diag)

    def test_endpoint_full_flow(self, tmp_path):
        app = self._app(tmp_path, FailureDiagnostic(ScriptedLLM({
            "explanation": "根因：元素缺失",
            "suggestion": "加可见性判断"})))
        c = TestClient(app)
        r = c.post("/api/intent/explain-failure",
                   json={"session": "s_d1"})
        body = r.json()
        assert r.status_code == 200
        assert body["failure_context"]["failed_count"] == 1
        assert body["explanation"] == "根因：元素缺失"

    def test_unknown_session_404(self, tmp_path):
        app = self._app(tmp_path, FailureDiagnostic(ScriptedLLM({})))
        c = TestClient(app)
        r = c.post("/api/intent/explain-failure",
                   json={"session": "nope"})
        assert r.status_code == 404

    def test_missing_session_400(self, tmp_path):
        app = self._app(tmp_path, FailureDiagnostic(ScriptedLLM({})))
        c = TestClient(app)
        assert c.post("/api/intent/explain-failure",
                      json={}).status_code == 400

    def test_no_diagnostic_501(self, tmp_path):
        app = create_app(journals=[])
        c = TestClient(app)
        assert c.post("/api/intent/explain-failure",
                      json={"session": "x"}).status_code == 501