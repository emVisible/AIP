"""Phase A 控制流引擎测试：loop.break/continue/字典 foreach/预算穿透。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))

import pytest

from apa_core.process import (  # noqa: E402
    ProcessDefinitionError,
    ProcessEngine,
    build_process,
)


def run_flow(name, steps, max_actions=50):
    sent = []
    proc = build_process({"process": {"id": name, "mode": "process",
        "trigger": {"type": "manual"}, "max_actions": max_actions,
        "steps": steps}})
    eng = ProcessEngine(proc, lambda a, p: (sent.append((a, p)),
                                             (True, {}))[1])
    eng.run.scopes["event"] = {}
    eng._run_from(0)
    return eng, [(a, p) for a, p in sent]


class TestLoopControlFlow:
    def test_break_exits_foreach(self):
        eng, pairs = run_flow("t", [{"id": "loop", "type": "foreach",
            "params": {"source": '[1,2,3,4,5]', "item_var": "n"},
            "body_steps": [
                {"id": "log", "action": "t.log",
                 "params": {"v": "{{n}}"}},
                {"id": "stop", "type": "loop.break"}]}])
        assert len(pairs) == 1
        assert eng.run.scopes["steps"]["loop"].get("breaked") is True

    def test_continue_skips_matching(self):
        eng, pairs = run_flow("t2", [{"id": "loop", "type": "foreach",
            "params": {"source": '[1,2,3,4]', "item_var": "n"},
            "body_steps": [
                {"id": "skip", "condition": "n % 2 == 0",
                 "type": "loop.continue"},
                {"id": "log", "action": "t.log",
                 "params": {"v": "{{n}}"}}]}])
        assert [p.get("v") for _, p in pairs] == [1, 3]

    def test_dict_source_key_value(self):
        eng, pairs = run_flow("t3", [{"id": "loop", "type": "foreach",
            "params": {"source": '{"a":1,"b":2}', "item_var": "kv",
                       "body_action": "t.use",
                       "body_params": {"k": "{{kv.key}}"}}}])
        assert [p.get("k") for _, p in pairs] == ["a", "b"]

    def test_while_body_steps_conditional_break(self):
        eng, pairs = run_flow("t4", [{"id": "w", "type": "while",
            "params": {"condition": "True", "max_iterations": 10},
            "body_steps": [
                {"id": "tick", "action": "t.tick"},
                {"id": "stop",
                 "condition": "steps.w.iterations >= 2",
                 "type": "loop.break"}]}], max_actions=50)
        w = eng.run.scopes["steps"]["w"]
        # body 顺序 [tick, stop]：break 检查在 tick 之后 → 第3轮命中
        assert w.get("breaked") is True
        assert len(pairs) == 3

    def test_stray_break_explicit_failure(self):
        with pytest.raises(ProcessDefinitionError,
                           match="outside any loop"):
            eng, _ = run_flow("t5", [{"id": "bad",
                                       "type": "loop.break"}])
            eng._run_from(0)

    def test_budget_propagates_from_loop_bodies(self):
        eng, pairs = run_flow("t6", [{"id": "loop", "type": "foreach",
            "params": {"source": '[1,2,3,4,5]', "item_var": "n"},
            "body_steps": [{"id": "x", "action": "t.x"}]}],
            max_actions=3)
        assert eng.run.outcome == "max_actions_exceeded"
        assert len(pairs) <= 3

