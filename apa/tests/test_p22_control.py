"""P22-M1 流程控制收尾测试：for_times / loop.infinite / 多条件文档模式。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))

import pytest

from apa_core.process import (  # noqa: E402
    ProcessDefinitionError,
    ProcessEngine,
    build_process,
)


def run_flow(name, steps, max_actions=100):
    sent = []
    proc = build_process({"process": {"id": name, "mode": "process",
        "trigger": {"type": "manual"}, "max_actions": max_actions,
        "steps": steps}})
    eng = ProcessEngine(proc, lambda a, p: (sent.append((a, p)),
                                             (True, {}))[1])
    eng.run.scopes["event"] = {}
    eng._run_from(0)
    return eng, [(a, p) for a, p in sent]


class TestForTimes:
    def test_basic_count(self):
        eng, pairs = run_flow("ft", [
            {"id": "loop", "type": "for_times",
             "params": {"count": 3},
             "body_steps": [{"id": "x", "action": "t.x"}]}])
        assert len(pairs) == 3
        assert eng.run.outcome == "success"

    def test_start_offset_item_var(self):
        _, pairs = run_flow("ft2", [
            {"id": "loop", "type": "for_times",
             "params": {"count": 3, "start": 10, "item_var": "i"},
             "body_steps": [{"id": "x", "action": "t.x",
                              "params": {"i": "{{i}}"}}]}])
        assert [p.get("i") for _, p in pairs] == [10, 11, 12]

    def test_break_inside(self):
        eng, pairs = run_flow("ft3", [
            {"id": "loop", "type": "for_times",
             "params": {"count": 10},
             "body_steps": [
                 {"id": "tick", "action": "t.tick"},
                 {"id": "early_exit", "type": "loop.break"}]}])
        assert len(pairs) == 1          # 第一轮 tick 后即 break

    def test_dynamic_count_from_template(self):
        proc = build_process({"process": {"id": "ft4b", "mode": "process",
            "trigger": {"type": "manual"}, "max_actions": 50,
            "steps": [
                {"id": "seed", "action": "t.seed"},
                {"id": "loop", "type": "for_times",
                 "params": {"count": "{{steps.seed.count}}"},
                 "body_steps": [{"id": "x", "action": "t.x"}]}]}})
        sent = []

        def send_fn(action, params):
            sent.append((action, params))
            if action == "t.seed":
                return True, {"count": 4}
            return True, {}

        from apa_core.process import ProcessEngine as PE
        eng = PE(proc, send_fn)
        eng.run.scopes["event"] = {}
        eng._run_from(0)
        assert len([p for a, p in sent if a == "t.x"]) == 4

    def test_negative_count_raises(self):
        with pytest.raises(ProcessDefinitionError, match="不能为负"):
            run_flow("ft5", [{"id": "loop", "type": "for_times",
                               "params": {"count": -1}}])

    def test_non_int_count_raises(self):
        with pytest.raises(ProcessDefinitionError,
                            match="必须为整数"):
            run_flow("ft6", [{"id": "loop", "type": "for_times",
                               "params": {"count": "abc"}}])

    def test_budget_inherited(self):
        eng, pairs = run_flow("ft7", [
            {"id": "loop", "type": "for_times",
             "params": {"count": 50},
             "body_steps": [{"id": "x", "action": "t.x"}]}],
            max_actions=4)
        assert eng.run.outcome == "max_actions_exceeded"
        assert len(pairs) <= 4


class TestLoopInfinite:
    def test_runs_until_max_iterations(self):
        eng, _ = run_flow("inf", [
            {"id": "spin", "type": "loop.infinite",
             "params": {"body_action": "t.tick",
                         "max_iterations": 5}}], max_actions=200)
        w = eng.run.scopes["steps"]["spin"]
        assert w["iterations"] == 5
        assert w.get("capped") is True

    def test_default_cap_is_process_budget(self):
        eng, _ = run_flow("inf2", [
            {"id": "spin", "type": "loop.infinite",
             "params": {"body_action": "t.tick"}}], max_actions=6)
        w = eng.run.scopes["steps"]["spin"]
        assert w["iterations"] <= 6

    def test_break_exits_early(self):
        eng, pairs = run_flow("inf3", [
            {"id": "spin", "type": "loop.infinite",
             "params": {"max_iterations": 100,
                         "body_action": "t.tick"},
             "body_steps": [
                 {"id": "quit",
                  "condition": "steps.spin.iterations >= 2",
                  "type": "loop.break"}]}], max_actions=200)
        w = eng.run.scopes["steps"]["spin"]
        assert w.get("breaked") is True


class TestMultiConditionDocMode:
    """多条件/else-if 链：AST 白名单已支持 and/or/not——文档化验证。"""

    def test_and_or_not_combination(self):
        eng, pairs = run_flow("mc", [
            {"id": "gate",
             "action": "mark.passed",
             "condition": ("steps.a.ok == 'yes' and "
                             "(steps.b.v > 10 or not steps.b.blocked)")},
        ])
        # 条件失败（无前置步骤）→ 流程 failed，但表达式合法不抛错
        assert eng.run.outcome in ("failed", "success")

    def test_else_if_chain_via_condition_goto(self):
        """else-if 链 = 多个 condition+goto 步骤顺序排列。"""
        eng, pairs = run_flow("chain", [
            {"id": "check_high",
             "action": "act.high",
             "condition": "event.data.amount > 100",
             "on_failure": {"goto": "check_mid"}},
            {"id": "check_mid",
             "action": "act.mid",
             "condition": "event.data.amount > 50",
             "on_failure": {"goto": "fallback"}},
            {"id": "fallback",
             "action": "act.low"},
        ], max_actions=20)
        # amount 未设置 → lookup None > 100 = False → 链式落到 fallback
        assert any(a == "act.low" for a, _ in pairs)