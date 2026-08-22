"""apa-core 单元测试：registry / policy / context / session / rules。"""
import pytest

from pathlib import Path

from apa_core.context import APAContextStore, ContextRefError
from apa_core.policy import PolicyConfig, PolicyDecision
from apa_core.registry import ActionRegistry, RegistryError, load_registries
from apa_core.rules import RuleBasedAgent, RuleEngine, interpolate
from apa_core.session import IllegalStateTransition, SessionStateMachine

APA_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def registries():
    return load_registries(
        APA_ROOT / "registries" / "core.yaml",
        APA_ROOT / "registries" / "browser.yaml",
        APA_ROOT / "registries" / "desktop.yaml",
        APA_ROOT / "registries" / "api.yaml")


class TestRegistry:
    def test_loads_all_entries(self, registries):
        assert len(registries) >= 20
        for name in ("context.get", "browser.click", "erp.order.approve",
                     "desktop.file.delete", "session.complete"):
            assert name in registries

    def test_idempotency_and_risk_from_registry_only(self, registries):
        e = registries.get("erp.order.approve")
        assert e.idempotency == "required"
        assert e.risk == "L2"
        assert e.timeout_ms > 0

    def test_params_schema_validation(self, registries):
        e = registries.get("browser.navigate")
        assert e.validate_params({"url": "https://x"}) == []
        assert e.validate_params({})  # missing required url
        assert e.validate_params("not-a-dict")

    def test_retries_requires_idempotency(self):
        with pytest.raises(RegistryError):
            ActionRegistry.from_dict({"x.y": {"idempotency": "none", "retries": 2}})

    def test_invalid_risk_rejected(self):
        with pytest.raises(RegistryError):
            ActionRegistry.from_dict({"x.y": {"risk": "L9"}})


class TestPolicy:
    def _entry(self, risk="L0"):
        from apa_core.registry import RegistryEntry
        return RegistryEntry(name="t.a", risk=risk)

    def test_l0_to_l2_auto_permit(self):
        p = PolicyConfig()
        for risk in ("L0", "L1", "L2"):
            d, _ = p.evaluate("t.a", self._entry(risk))
            assert d == PolicyDecision.PERMIT

    def test_l3_l4_require_human(self):
        p = PolicyConfig()
        for risk in ("L3", "L4"):
            d, _ = p.evaluate("t.a", self._entry(risk))
            assert d == PolicyDecision.REQUIRE_HUMAN

    def test_deny_and_approval_lists(self):
        p = PolicyConfig(deny=["t.b"], require_approval=["t.c"])
        assert p.evaluate("t.b", self._entry())[0] == PolicyDecision.REJECT
        assert p.evaluate("t.c", self._entry())[0] == PolicyDecision.REQUIRE_HUMAN

    def test_conditional_rule(self):
        p = PolicyConfig(rules=[
            {"action": "t.d", "when": {"amount": 5}, "decision": "reject"}])
        e = self._entry()
        assert p.evaluate("t.d", e, {"amount": 5})[0] == PolicyDecision.REJECT
        assert p.evaluate("t.d", e, {"amount": 9})[0] == PolicyDecision.PERMIT


class TestContext:
    def test_ref_format_enforced(self):
        store = APAContextStore("s1")
        store.put(store.make_ref("s1", "a"), {"k": 1})
        with pytest.raises(ContextRefError):
            store.put("ctx_s2_a", {"k": 1})

    def test_wildcard_forbidden(self):
        store = APAContextStore("s1")
        store.put(store.make_ref("s1", "a"), {"k": 1})
        data, err = store.get(store.make_ref("s1", "a"), ["*"])
        assert data is None and err == "context.wildcard_forbidden"

    def test_field_acl(self):
        store = APAContextStore("s1")
        ref = store.make_ref("s1", "o")
        store.put(ref, {"order_id": "PO-1", "amount": 5, "internal": True},
                  acl={"internal": ["auditor"]},
                  allowed_fields=["order_id", "amount"])
        data, _ = store.get(ref, ["order_id"], principal="dsh")
        assert data == {"order_id": "PO-1"}
        data, _ = store.get(ref, None, principal="dsh")  # 未声明字段不可见
        assert "internal" not in data
        data, _ = store.get(ref, ["internal"], principal="auditor")  # ACL 外字段不可见
        assert data == {}

    def test_snapshot_and_invalidate(self):
        store = APAContextStore("s1")
        ref = store.make_ref("s1", "a")
        store.put(ref, {"k": 1}, allowed_fields=["k"])
        assert store.snapshot(ref) == {"k": 1}
        store.invalidate(ref)
        _, err = store.get(ref, ["k"])
        assert err == "context.not_found"


class TestSessionStateMachine:
    def test_happy_path(self):
        sm = SessionStateMachine("s")
        sm.start()
        sm.complete("success")
        assert sm.state == "COMPLETED"

    def test_suspend_resume(self):
        sm = SessionStateMachine("s")
        sm.start()
        sm.suspend_for_human("ht1")
        assert sm.state == "SUSPENDED"
        # 多个挂起任务：完成一个仍 SUSPENDED
        sm.record.human_tasks.append("ht2")
        sm.resume_after_human("ht1")
        assert sm.state == "SUSPENDED"
        sm.resume_after_human("ht2")
        assert sm.state == "RUNNING"

    def test_illegal_transition(self):
        sm = SessionStateMachine("s")
        with pytest.raises(IllegalStateTransition):
            sm.transition("COMPLETED")  # INITIALIZING → COMPLETED 非法

    def test_terminal_is_final(self):
        sm = SessionStateMachine("s")
        sm.start()
        sm.fail("boom")
        with pytest.raises(IllegalStateTransition):
            sm.transition("RUNNING")  # FAILED 为终态


class TestRules:
    def test_interpolate(self):
        assert interpolate("{{a}}/{{b}}", {"a": 1}) == "1/{{b}}"

    def test_event_matching_with_compare(self):
        eng = RuleEngine([
            {"name": "small", "if": {"event": "e1", "data": {"amount": {"lt": 100}}},
             "then": {"action": "approve"}},
            {"name": "big", "if": {"event": "e1", "data": {"amount": {"ge": 100}}},
             "then": {"action": "escalate"}},
        ])
        assert eng.evaluate_event("e1", {"amount": 45})["action"] == "approve"
        assert eng.evaluate_event("e1", {"amount": 450})["action"] == "escalate"

    def test_result_matching(self):
        eng = RuleEngine([
            {"if": {"action_result": "browser.extract", "status": "ok"},
             "then": {"action": "session.complete"}},
        ])
        assert eng.evaluate_result("browser.extract", "ok", {})["action"] == "session.complete"
        assert eng.evaluate_result("browser.extract", "failed", {}) is None

    def test_once_semantics_via_agent(self):
        from aip import AIPPeer, make_event
        eng = RuleEngine([
            {"name": "r1", "once": True,
             "if": {"event": "e1"}, "then": {"action": "a1"}},
        ])
        agent = RuleBasedAgent(AIPPeer(source="ag", session_id="s"), eng)
        for seq in (1, 2):  # 同名事件到达两次（新 id）
            m = make_event("s", "ex", "e1", data={})
            m.seq = seq
            agent.on_message(m.to_dict())
        assert len(agent.sent) == 1  # 只执行一次
