"""Phase B 策略二：自由编译器测试（Registry 词表 + 双重校验）。"""
import json
from pathlib import Path

import pytest

from apa_core.intent.compiler import IntentCompiler
from apa_core.intent.free import AutoIntentCompiler, FreeIntentCompiler
from apa_core.intent.templates import TEMPLATE_REGISTRY
from apa_core.registry import load_registries

APA = Path(__file__).resolve().parents[1]


def _reg():
    return load_registries(*[str(p) for p in sorted(
        (APA / "registries").glob("*.yaml"))])


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def chat(self, messages):
        self.prompts.append(messages[-1]["content"])
        r = self.replies.pop(0)
        return r if isinstance(r, str) else json.dumps(r)


def _proc(steps, max_actions=20):
    return {"questions": [], "process": {
        "id": "free_x", "mode": "process",
        "trigger": {"type": "manual"},
        "max_actions": max_actions, "steps": steps}}


class TestFreeCompiler:
    def test_valid_assembly_registry_checked(self):
        llm = Scripted([_proc([
            {"id": "open", "action": "browser.navigate",
             "params": {"url": "https://x"}},
            {"id": "shot", "action": "browser.take_screenshot"}])])
        free = FreeIntentCompiler(_reg(), llm)
        r = free.compile("打开页面并截图")
        assert r.ok and "https://x" in r.process_yaml
        # 词表注入断言：catalog 必须出现在 prompt 中
        assert "browser.navigate" in llm.prompts[0]

    def test_hallucinated_action_hard_rejects(self):
        llm = Scripted([_proc([
            {"id": "s", "action": "magic.autoclick", "params": {}}])])
        free = FreeIntentCompiler(_reg(), llm)
        r = free.compile("自动点击一切")
        assert not r.ok
        assert any("magic.autoclick" in q for q in r.questions)

    def test_empty_steps_precise_error(self):
        llm = Scripted([_proc([])])
        r = FreeIntentCompiler(_reg(), llm).compile("什么都不做")
        assert not r.ok and "steps 为空" in (r.error or "")

    def test_duplicate_ids_rejected(self):
        llm = Scripted([_proc([
            {"id": "dup", "action": "browser.navigate",
             "params": {"url": "u"}},
            {"id": "dup", "action": "browser.click",
             "params": {"target": "b"}}])])
        r = FreeIntentCompiler(_reg(), llm).compile("重复 id")
        assert not r.ok

    def test_max_actions_clamped_to_cap(self):
        llm = Scripted([_proc([
            {"id": f"s{i}", "action": "browser.navigate",
             "params": {"url": "u"}} for i in range(4)],
            max_actions=99999)])
        r = FreeIntentCompiler(_reg(), llm).compile(
            "多步流程", ) if False else None
        # cap 逻辑经 compile 内部钳位（99999 → ≤cap）
        free = FreeIntentCompiler(_reg(), llm, max_actions_cap=50)
        r = free.compile("四步导航流程")
        assert r.ok
        assert "max_actions: 50" in r.process_yaml

    def test_llm_failure_degrades(self):
        class Boom:
            def chat(self, messages):
                raise RuntimeError("net down")

        r = FreeIntentCompiler(_reg(), Boom()).compile("监控价格")
        assert not r.ok and "llm_error" in (r.error or "")


class TestAutoRouting:
    def test_template_hit_routes_template(self):
        llm_tpl = Scripted([json.dumps({
            "filled": {}, "questions": []})])
        tpl = IntentCompiler(TEMPLATE_REGISTRY, llm_tpl)
        free_llm = Scripted([])
        auto = AutoIntentCompiler(tpl,
                                  FreeIntentCompiler(_reg(), free_llm))
        r = auto.compile("客服质检 情绪分类")
        assert r.template_id == "cs-quality-check"
        assert free_llm.prompts == []     # 未动用自由编译

    def test_no_template_falls_to_free(self):
        tpl = IntentCompiler(TEMPLATE_REGISTRY, Scripted([]))
        llm_free = Scripted([_proc([
            {"id": "n", "action": "browser.navigate",
             "params": {"url": "u"}}])])
        auto = AutoIntentCompiler(tpl,
                                  FreeIntentCompiler(_reg(), llm_free))
        r = auto.compile("给老板发周报邮件")
        assert r.ok is True or r.questions
        assert llm_free.prompts           # 自由编译被调用