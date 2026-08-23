"""dataops.* 动作（data/file/string/email）经 Gateway 校验链放行验证。

此前这些动作只有执行器实现、无 registry 条目 —— Gateway 会以
"not in registry" 拒绝。registries/dataops.yaml 补齐后必须全链路可用。
"""
from pathlib import Path

import pytest

APA_DIR = Path(__file__).resolve().parents[1]

from aip import AIPPeer  # noqa: E402

from apa_core.embedded import EmbeddedGateway  # noqa: E402
from apa_core.policy import PolicyConfig  # noqa: E402
from apa_core.registry import load_registries  # noqa: E402
from apa_core.rules import RuleBasedAgent  # noqa: E402


class CaptureExecutor:
    """记录收到的 action 名（不回结果：本测试只验证校验链放行）。"""

    def __init__(self, sid: str) -> None:
        self.peer = AIPPeer(source="exec_cap", session_id=sid)
        self.seen: list[str] = []

    def on_message(self, raw: dict):
        cls, msg = self.peer.handle(raw)
        if cls == "accept" and msg.type == "action":
            self.seen.append(msg.payload.get("name", ""))
        return None


def _all_registries():
    return load_registries(*[
        str(p) for p in sorted((APA_DIR / "registries").glob("*.yaml"))])


def _run_rule_action(sid: str, action: str, params: dict) -> CaptureExecutor:
    gw = EmbeddedGateway(
        sid, registry=_all_registries(), policy=PolicyConfig(),
        identities={"executor": "exec_cap", "agent": "ag_cap"})

    ex = CaptureExecutor(sid)
    gw.attach_executor(ex, "exec_cap")
    agent = RuleBasedAgent(
        AIPPeer(source="ag_cap", session_id=sid),
        [{"name": "go", "once": True,
          "if": {"event": "erp.batch.ready"},
          "then": {"action": action, "params": params}},
         {"name": "fin", "once": True,
          "if": {"event": "session.timeout"},
          "then": {"action": "session.complete",
                   "params": {"outcome": "success"}}}],
    )
    gw.attach_agent(agent, "ag_cap")

    # 执行器语义事件 → gateway 分发 → 规则触发 → action 回到执行器
    ex.peer.send_event("erp.batch.ready", {})
    ex.peer.send_event("session.timeout", {})
    return ex


class TestDataopsGatewayPass:
    @pytest.mark.parametrize("action,params", [
        ("data.create", {"columns": ["a"], "rows": [[1]]}),
        ("data.filter", {"source": "t", "column": "amount",
                         "op": ">", "value": 5}),
        ("data.sort", {"source": "t", "column": "amount"}),
        ("data.to_csv", {"source": "t"}),
        ("file.read_text", {"path": "/tmp/x.txt"}),
        ("file.write_text", {"path": "/tmp/x.txt", "content": "hi"}),
        ("string.replace", {"text": "ab", "old": "a", "new": "b"}),
        ("string.split", {"text": "a,b"}),
    ])
    def test_action_reaches_executor(self, action, params):
        ex = _run_rule_action(f"s_dataops_{action.replace('.', '_')}",
                              action, params)
        assert action in ex.seen, f"{action} 被 Gateway 拒绝: {ex.seen}"

    def test_email_send_registered(self):
        ex = _run_rule_action("s_email_reg", "email.send",
                              {"to": "x@y.z", "subject": "t"})
        assert "email.send" in ex.seen

    def test_registry_total(self):
        reg = _all_registries()
        names = reg.names()
        for must in ("data.filter", "email.send", "excel.append_rows",
                     "ocr.extract", "browser.extract_table"):
            assert must in names, f"{must} 缺失于 registry"
