"""M2 流程控制测试：while 循环 + log 节点 + delay/count 配套。"""
import pytest

from apa_core.process import (
    ProcessDefinitionError,
    ProcessEngine,
    build_process,
)

from apa_executors.data_executor import DataExecutor  # noqa: F401


def _mk_engine(steps, send_fn, max_actions=50):
    proc = build_process({"process": {
        "id": "t_while", "mode": "process",
        "trigger": {"type": "manual"},
        "max_actions": max_actions,
        "steps": steps,
    }})
    eng = ProcessEngine(proc, send_fn)
    eng.run.scopes["event"] = {}
    return eng


class TestWhileLoop:
    def test_condition_exit_and_scope_visibility(self):
        """body 结果写入 steps.<out>.last → 条件逐轮可见。"""
        state = {"n": 0}

        def send_fn(action, params):
            state["n"] += 1
            return True, {"value": state["n"]}

        eng = _mk_engine([{
            "id": "w", "type": "while",
            "params": {
                "condition": "steps.w.last.value < 3",
                "max_iterations": 10,
                "body_action": "test.inc",
            },
        }], send_fn)
        eng._run_from(0)

        assert eng.run.outcome == "success"
        assert state["n"] == 3
        w = eng.run.scopes["steps"]["w"]
        assert w["iterations"] == 3
        assert w["capped"] is False
        assert w["last"]["value"] == 3

    def test_max_iterations_cap(self):
        """条件恒真 → 达上限停止，输出 capped=True，整体 success。"""
        calls = []

        def send_fn(action, params):
            calls.append(1)
            return True, {}

        eng = _mk_engine([{
            "id": "w", "type": "while",
            "params": {
                "condition": "True",
                "max_iterations": 5,
                "body_action": "test.tick",
            },
        }], send_fn)
        eng._run_from(0)
        assert eng.run.outcome == "success"
        assert len(calls) == 5
        assert eng.run.scopes["steps"]["w"]["capped"] is True

    def test_max_iterations_required(self):
        for bad in ({"condition": "True"},
                    {"max_iterations": 3}):
            eng = _mk_engine([{"id": "w", "type": "while",
                               "params": dict(bad)}],
                             lambda a, p: (True, {}))
            with pytest.raises(ProcessDefinitionError):
                eng._run_from(0)

    def test_body_failure_routes_error_handler(self):
        def send_fn(action, params):
            return False, {"code": "boom"}

        eng = _mk_engine([
            {"id": "w", "type": "while",
             "params": {"condition": "True", "max_iterations": 9,
                        "body_action": "bad.op"}},
            {"id": "fix", "action": "noop.ok"},
        ], send_fn)
        # 给 while 挂 error handler → goto fix
        eng.proc.steps[0].on_failure = {"goto": "fix"}
        # fix 步骤用成功 sender 不可能（sender 固定失败）→ 只验证跳转发生
        eng._run_from(0)
        logged = [s for s in eng.run.steps if s.get("step") == "w"]
        assert logged and logged[-1]["status"] == "failed"

    def test_budget_guard_inside_loop(self):
        calls = []

        def send_fn(action, params):
            calls.append(1)
            return True, {"value": len(calls)}

        eng = _mk_engine([{
            "id": "w", "type": "while",
            "params": {"condition": "True", "max_iterations": 100,
                       "body_action": "t"},
        }], send_fn, max_actions=4)
        eng._run_from(0)
        assert eng.run.outcome == "max_actions_exceeded"
        assert len(calls) <= 4

    def test_condition_only_poll_shape(self):
        """无 body 的条件等待形态：立即为假则零迭代退出。"""
        eng = _mk_engine([{
            "id": "w", "type": "while",
            "params": {"condition": "False", "max_iterations": 3},
        }], lambda a, p: (True, {}))
        eng._run_from(0)
        w = eng.run.scopes["steps"]["w"]
        assert w["iterations"] == 0 and w["capped"] is False


class TestLogNode:
    def test_log_renders_templates(self):
        sent = []
        eng = _mk_engine([
            {"id": "say", "type": "log",
             "params": {"message": "处理 {{event.data.oid}} 完成"}},
        ], lambda a, p: (sent.append(a), (True, {}))[1])
        eng.run.scopes["event"] = {"name": "e", "data": {"oid": "X1"}}
        eng._run_from(0)
        entry = [s for s in eng.run.steps if s.get("type") == "log"]
        assert entry and entry[0]["message"] == "处理 X1 完成"


class TestDelayAndCount:
    def test_delay_respects_cap(self, monkeypatch):
        slept = []
        import time as _t
        monkeypatch.setattr(_t, "sleep",
                            lambda s: slept.append(s))
        from apa_executors.data_executor import DataExecutor

        ex = DataExecutor.__new__(DataExecutor)
        ex._tables = {}
        ok, o = ex._execute_action("core.delay", {"seconds": 99999})
        assert ok and o["slept"] == 300.0
        assert slept == [300.0]

    def test_count_zero_and_filled(self):
        from apa_executors.data_executor import DataExecutor

        ex = DataExecutor.__new__(DataExecutor)
        ex._tables = {}
        def run(n, **kw):
            ok, out = ex._execute_action(n, kw)
            assert ok, (n, out)
            return out
        assert run("data.count", source="none")["count"] == 0
        run("data.create", key="t", columns=["a"],
            rows=[[1], [2], [3]])
        assert run("data.count", source="t")["count"] == 3