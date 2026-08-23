"""Phase 12：.flow 文本格式编译器测试。"""
import pytest

from apa_core.flow import (
    FlowError,
    decompile_flow,
    parse_flow,
    roundtrip_check,
)
from apa_core.process import build_process


SAMPLE_FLOW = """\
# 采购订单自动审批
trigger erp.order.approval_requested
max_actions 50

context.get ref={{context}} fields=[order_id,amount,vendor] → order

erp.order.approve order_id={{order.order_id}} approver=apa_system \\
    if order.amount < 100000 on_failure goto escalate

handler escalate
    human.task.create task_type=exception assignee_role=proc_mgr
"""


class TestFlowParser:
    def test_parse_basic(self):
        flow = """
        trigger e.x.y
        max_actions 10

        browser.click target=btn1
        api.http.post url=https://x json={"k":"v"} → result
        """
        proc = parse_flow(flow.strip())
        assert len(proc["steps"]) == 2
        assert proc["steps"][0]["action"] == "browser.click"
        assert proc["steps"][1]["params"]["url"] == "https://x"
        assert proc["steps"][1]["output_as"] == "result"

    def test_trigger_and_meta(self):
        flow = "trigger e.a.b\nmax_actions 20\nid my_flow"
        proc = parse_flow(flow)
        assert proc["trigger"]["name"] == "e.a.b"
        assert proc["max_actions"] == 20
        assert proc["id"] == "my_flow"

    def test_condition_if(self):
        flow = "browser.click target=b if amount < 100000"
        proc = parse_flow(flow)
        assert proc["steps"][0]["condition"] == "amount < 100000"

    def test_condition_unless(self):
        flow = "a.b x=1 unless ready"
        proc = parse_flow(flow)
        assert "not (ready)" in proc["steps"][0]["condition"]

    def test_on_failure_goto(self):
        flow = "a.b x=1 on_failure goto retry_handler"
        proc = parse_flow(flow)
        assert proc["steps"][0]["on_failure"]["goto"] == "retry_handler"

    def test_output_arrow(self):
        flow = "a.b x=1 → my_result"
        proc = parse_flow(flow)
        assert proc["steps"][0]["output_as"] == "my_result"

    def test_c3_rejection(self):
        with pytest.raises(FlowError, match="C3"):
            parse_flow("a.b idempotency=required")

    def test_comments_and_blanks(self):
        flow = "# comment\n\n  a.b x=1  # inline comment not supported yet"
        proc = parse_flow(flow.strip())
        assert len(proc["steps"]) >= 1

    def test_metadata_only_flow(self):
        """无步骤流程合法（仅元信息）。"""
        proc = parse_flow("trigger e.a.b\nmax_actions 20")
        assert proc["trigger"]["name"] == "e.a.b"


class TestFlowDecompile:
    def test_decompile_produces_readable_text(self):
        proc = {
            "process": {
                "id": "test",
                "trigger": {"type": "event", "name": "e.a.b"},
                "max_actions": 50,
                "steps": [
                    {"id": "s1", "action": "browser.click",
                     "params": {"target": "btn"}},
                    {"id": "s2", "action": "api.http.post",
                     "condition": "{{ steps.s1.ok }}",
                     "params": {"url": "https://x"}},
                ],
                "error_handlers": {},
            }
        }
        text = decompile_flow(proc)
        assert "browser.click" in text
        assert "api.http.post" in text
        assert "if" in text.lower()


class TestRoundtrip:
    def test_flow_to_yaml_to_flow_semantic_preserved(self):
        from apa_core.flow import parse_flow as pf
        from apa_core.flow import decompile_flow as df

        flow_text = (
            "trigger e.a.b\n"
            "max_actions 50\n"
            "\n"
            "browser.navigate url=https://x.corp\n"
            "browser.click target=btn1\n"
        )
        # 解析为 dict（build_process 格式）
        proc = pf(flow_text.strip())
        # build_process 需要 wrapper
        wrapped = {"process": proc}
        # 反编译
        text = df(wrapped)
        # 重新解析
        re_parsed = pf(text)

        orig_steps = proc["steps"]
        new_steps = re_parsed["steps"]
        assert len(orig_steps) == len(new_steps)
        for o, n in zip(orig_steps, new_steps):
            assert o["action"] == n["action"]
            assert o.get("params") == n.get("params", {})


class TestFlowIntegration:
    def test_compiled_flow_builds_valid_process(self):
        flow = (
            "trigger e.test.a\n"
            "\n"
            "api.http.post url=https://httpbin.org/post\n"
        )
        proc = parse_flow(flow.strip())
        # build_process 应能接受此结构
        from apa_core.process import build_process
        built = build_process({"process": proc})
        assert built.steps[0].action == "api.http.post"