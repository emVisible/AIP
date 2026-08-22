"""端到端测试：BrowserExecutor + EmbeddedGateway + 规则引擎（MockPage）。"""
import subprocess
import sys
from pathlib import Path

import pytest

from aip import AIPPeer

from apa_core.embedded import EmbeddedGateway
from apa_core.policy import PolicyConfig
from apa_core.registry import load_registries
from apa_core.rules import RuleBasedAgent, RuleEngine
from apa_executors.browser_executor import BrowserExecutor
from apa_sdk.semantic_adapter import SemanticAdapter
from apa_sdk.testing import MockElement, MockPage

APA_ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
APA_DIR = APA_ROOT / "apa"
HERE = Path(__file__).resolve().parent


def build_demo(session="s_hello_001"):
    registries = load_registries(
        APA_DIR / "registries" / "core.yaml",
        APA_DIR / "registries" / "browser.yaml",
        APA_DIR / "registries" / "desktop.yaml",
        APA_DIR / "registries" / "api.yaml")
    gw = EmbeddedGateway(
        session, registry=registries, policy=PolicyConfig(),
        identities={"executor": "browser_01", "agent": "rule_01"},
        process_id="e2e", tenant_id="test")

    page = MockPage()
    page.title = "APA 演示 — 采购订单待办"
    page.elements = [
        MockElement(role="heading", text="待审批采购订单", id="page-title"),
        MockElement(role="cell", text="PO-5678", attrs={"data-order-id": "PO-5678"}),
        MockElement(role="cell", text="¥45,000.00", data_apa_id="order-amount-1",
                    attrs={"class": "order-amount"}),
        MockElement(role="cell", text="示例供应商A", data_apa_id="vendor-1",
                    attrs={"class": "vendor-name"}),
        MockElement(role="button", text="批准", data_apa_id="approve-btn-1",
                    attrs={"class": "approve"}),
        MockElement(role="button", text="驳回", data_apa_id="reject-btn-1",
                    attrs={"class": "reject"}),
        MockElement(role="cell", text="待处理", data_apa_id="result"),
    ]
    orig_click = page.click

    def click(target, force=False):
        orig_click(target, force=force)
        if target == "approve-btn-1":
            for el in page.elements:
                if el.data_apa_id == "result":
                    el.text = "已批准订单 PO-5678"
    page.click = click

    executor = BrowserExecutor("browser_01", session, page=page,
                               adapter=SemanticAdapter.from_yaml(
                                   str(APA_DIR / "examples/hello-rpa/schema.yaml")))
    agent = RuleBasedAgent(
        AIPPeer(source="rule_01", session_id=session),
        RuleEngine.from_yaml(str(APA_DIR / "examples/hello-rpa/rules.yaml")))

    gw.attach_executor(executor, "browser_01")
    gw.attach_agent(agent, "rule_01")
    gw.run()
    return gw, executor, agent, page


class TestHelloRpaE2E:
    def test_full_loop_mock(self):
        gw, executor, agent, page = build_demo()
        page.goto("https://demo.corp/test_page/index.html")
        executor.trigger_navigate(page.url)
        assert agent.done, agent.steps
        summary = gw.summary()
        assert summary["state"] == "COMPLETED"
        result = executor.context_store.snapshot("ctx_s_hello_001_result")
        assert result and "已批准订单 PO-5678" in result["result"]

    def test_no_event_storm_on_unchanged_state(self):
        gw, executor, agent, page = build_demo()
        page.goto("https://demo.corp/test_page/index.html")
        executor.trigger_navigate(page.url)
        before = len(gw.gateway.emitted)
        executor.trigger_navigate(page.url)  # 状态未变 → 不再发事件
        assert len(gw.gateway.emitted) == before

    def test_high_value_order_not_approved(self):
        gw, executor, agent, page = build_demo()
        # 改成大额订单 → 规则不命中 → 无点击
        for el in page.elements:
            if el.data_apa_id == "order-amount-1":
                el.text = "¥350,000.00"
        page.goto("https://demo.corp/test_page/index.html")
        executor.trigger_navigate(page.url)
        assert not agent.done or all(
            "browser.click" not in step for step in agent.steps)


class TestDryRun:
    def test_l1_simulated_in_dry_run(self):
        from apa_sdk.dry_run import DryRunExecutor

        class Real(DryRunExecutor):
            def _real_execute(self, name, params):
                self.real_calls.append(name)
                return True, {}

        registries = load_registries(APA_DIR / "registries" / "browser.yaml")
        ex = Real("ex", "s_dry", registry=registries, dry_run=True)
        ex.real_calls = []
        ok, data = ex._execute_action("browser.click", {"target": "b"})
        assert ok and data["dry_run"] is True and not ex.real_calls
        ok, data = ex._execute_action("browser.extract", {"selectors": {}})
        assert ok and not data.get("dry_run") and ex.real_calls == ["browser.extract"]


class TestCircuitBreaker:
    def test_opens_after_threshold(self):
        from apa_sdk.resilient import CircuitOpenError, ExecutorCircuitBreaker
        cb = ExecutorCircuitBreaker("target-x", failure_threshold=3,
                                    recovery_timeout_s=60)
        for _ in range(2):
            cb.on_failure()
        cb.before_action()  # 仍 CLOSED
        cb.on_failure()
        with pytest.raises(CircuitOpenError):
            cb.before_action()


@pytest.mark.e2e
class TestSubprocess:
    def test_hello_rpa_mock_mode(self):
        r = subprocess.run(
            [sys.executable, str(APA_DIR / "examples/hello-rpa/run.py"), "--mock"],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "RESULT: OK" in r.stdout

    def test_conformance_suite(self):
        r = subprocess.run(
            [sys.executable, str(APA_DIR / "conformance/run.py")],
            capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "20/20 passed" in r.stdout