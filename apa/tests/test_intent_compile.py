"""Phase B 意图编译器测试：模板检索/槽位填充/澄清协议/API 注入。"""
import json
from pathlib import Path

import pytest

from apa_core.intent.compiler import CompileResult, IntentCompiler
from apa_core.intent.templates import TEMPLATE_REGISTRY


class ScriptedLLM:
    """chat() 桩：按序返回脚本；记录 prompt 供断言。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def chat(self, messages):
        self.prompts.append(messages[-1]["content"])
        r = self.replies.pop(0) if self.replies else "{}"
        return r if isinstance(r, str) else json.dumps(r)


@pytest.fixture()
def compiler():
    llm = ScriptedLLM([])
    ic = IntentCompiler(TEMPLATE_REGISTRY, llm)
    return ic, llm


class TestTemplateRetrieval:
    def test_price_monitor_top_match(self, compiler):
        ic, _ = compiler
        tid, ratio = ic.pick_template(
            "每天早上帮我监控竞品价格，涨了就预警")
        assert tid == "price-monitor" and ratio > 0

    def test_cs_quality_match(self, compiler):
        ic, _ = compiler
        tid, _ = ic.pick_template("客服聊天记录做情绪分类质检")
        assert tid == "cs-quality-check"

    def test_no_match(self, compiler):
        ic, _ = compiler
        tid, _ = ic.pick_template("帮我写一首诗")
        assert tid is None


class TestSlotFilling:
    def test_full_fill_compiles_yaml(self):
        llm = ScriptedLLM([json.dumps({
            "filled": {"url": "https://shop.com/p1",
                        "threshold": "100",
                        "notify_to": "ops@corp.com"},
            "questions": [],
        })])
        ic = IntentCompiler(TEMPLATE_REGISTRY, llm)
        r = ic.compile("监控 https://shop.com/p1 价格超100 就通知 ops@corp.com")
        assert r.ok, (r.questions, r.error)
        assert r.process_yaml and "{{url}}" not in r.process_yaml
        assert "shop.com/p1" in r.process_yaml
        # 幻觉防线：产出动作必须存在于 registry
        from apa_core.registry import load_registries
        reg = load_registries(*[
            str(p) for p in sorted((Path(__file__).resolve().parents[1]
                                    / "registries").glob("*.yaml"))])
        for line in r.process_yaml.splitlines():
            if line.strip().startswith("action:"):
                act = line.split("action:")[1].strip()
                assert act in reg.names(), f"幻觉动作 {act}"

    def test_missing_slot_becomes_question(self):
        llm = ScriptedLLM([json.dumps({
            "filled": {"threshold": "100"},
            "questions": ["请提供竞品页面 URL", "通知发给谁？"],
        })])
        ic = IntentCompiler(TEMPLATE_REGISTRY, llm)
        r = ic.compile("监控竞品价格，超过100就提醒")
        assert not r.ok
        assert any("URL" in q for q in r.questions)
        assert any("谁" in q for q in r.questions)

    def test_unresolved_placeholder_forces_question(self, ):
        """LLM 谎称填完但 YAML 仍留占位 → 兜底转澄清。"""
        llm = ScriptedLLM([json.dumps({"filled": {}, "questions": []})])
        ic = IntentCompiler(TEMPLATE_REGISTRY, llm)
        r = ic.compile("监控价格")
        assert not r.ok
        assert r.questions, "占位符未填必须产生澄清问题"

    def test_llm_failure_degrades(self):
        class Boom:
            def chat(self, messages):
                raise RuntimeError("net down")

        ic = IntentCompiler(TEMPLATE_REGISTRY, Boom())
        r = ic.compile("监控竞品价格")
        assert not r.ok and "llm_error" in (r.error or "")


class TestApiEndpoint:
    def test_injected_compiler_via_api(self):
        from apa_core.api import create_app
        from starlette.testclient import TestClient

        llm = ScriptedLLM([json.dumps({
            "filled": {"url": "u", "threshold": "1",
                        "notify_to": "a@b"},
            "questions": []})])
        ic = IntentCompiler(TEMPLATE_REGISTRY, llm)
        app = create_app(journals=[], intent_compiler=ic)
        c = TestClient(app)
        r = c.post("/api/intent/compile",
                   json={"utterance": "监控价格"})
        body = r.json()
        assert r.status_code == 200
        assert body["ok"] is True
        assert body["template_id"] == "price-monitor"
        for slot in ("url", "threshold", "notify_to"):
            assert "{{" + slot + "}}" not in body["process_yaml"]

    def test_without_compiler_501(self):
        from apa_core.api import create_app
        from starlette.testclient import TestClient

        app = create_app(journals=[])
        c = TestClient(app)
        assert c.post("/api/intent/compile",
                      json={"utterance": "x"}).status_code == 501