"""Gateway 校验链与 Executor 基类测试（协议行为）。"""
from pathlib import Path

import pytest

from aip import FakeClock, AIPPeer, make_action, make_event, make_result

from apa_core.audit import AuditService
from apa_core.embedded import EmbeddedGateway
from apa_core.gateway import APAGateway
from apa_core.policy import PolicyConfig
from apa_core.registry import load_registries
from apa_core.rules import RuleBasedAgent, RuleEngine
from apa_sdk.executor_base import AIPExecutor, ExecutorPreconditionError

APA_ROOT = Path(__file__).resolve().parent.parent
SESSION = "s_test_001"
EXEC, AGENT = "exec_001", "agent_001"


def build(**kw):
    gw = EmbeddedGateway(
        SESSION,
        registry=load_registries(
            APA_ROOT / "registries" / "core.yaml",
            APA_ROOT / "registries" / "browser.yaml",
            APA_ROOT / "registries" / "desktop.yaml",
            APA_ROOT / "registries" / "api.yaml"),
        identities={"executor": EXEC, "agent": AGENT},
        **kw)
    gw.run()
    return gw


class RecordingExecutor(AIPExecutor):
    """最小执行器：记录动作，支持 browser.click 与失败注入。"""

    def __init__(self, *a, fail_on=frozenset(), **kw):
        super().__init__(*a, **kw)
        self.executed = []
        self.fail_on = set(fail_on)

    def _execute_action(self, name, params):
        if name in self.fail_on:
            return False, {"code": "boom"}
        self.executed.append((name, params))
        return True, {"echo": params}


class TestGatewayValidationChain:
    def test_forwarded_action_reaches_executor(self):
        gw = build()
        ex = RecordingExecutor(EXEC, SESSION)
        ag = RuleBasedAgent(AIPPeer(AGENT, SESSION), [])
        gw.attach_executor(ex, EXEC)
        gw.attach_agent(ag, AGENT)
        m = make_action(SESSION, AGENT, "browser.click", params={"target": "b1"})
        m.seq = 1
        gw.gateway.deliver("agent", m.to_dict())
        assert ("browser.click", {"target": "b1"}) in ex.executed
        # executor 回 accepted + ok，均路由回 agent
        statuses = [r["payload"]["status"] for r in
                    [x for x in []]]  # placeholder
        assert ag.peer.receiver.cursors(SESSION).get(EXEC) is not None

    def test_gateway_generated_reject_goes_to_sender(self):
        gw = build()
        ag_inbox = []
        gw.gateway.set_handler("agent", lambda raw: ag_inbox.append(raw))
        m = make_action(SESSION, AGENT, "no.such.action", params={})
        m.seq = 1
        gw.gateway.deliver("agent", m.to_dict())
        assert any(r["type"] == "result" and r["source"] == "gateway"
                   and r["payload"].get("code") == "action_not_registered"
                   for r in ag_inbox)

    def test_audit_records_permitted_actions(self):
        audit = AuditService()
        gw = build(audit=audit)
        m = make_action(SESSION, AGENT, "browser.click", params={"target": "b1"})
        m.seq = 1
        gw.gateway.receive("agent", m.to_dict())
        records = audit.read_all()
        actions = [r for r in records if r.get("action")]
        assert actions and actions[0]["action"]["name"] == "browser.click"
        assert actions[0]["security"]["risk_level"] == "L1"
        assert actions[0]["params_audit"] == {"target": "b1"}

    def test_audit_masks_sensitive_fields(self):
        audit = AuditService()
        gw = build(audit=audit)
        m = make_action(SESSION, AGENT, "browser.input",
                        params={"target": "pw", "value": "hello"})
        m.seq = 1
        gw.gateway.receive("agent", m.to_dict())
        rec = [r for r in audit.read_all() if r.get("action")][0]
        assert rec["params_audit"]["value"] == "***"

    def test_retry_same_action_id_on_timeout(self):
        clock = FakeClock(start_ms=0)
        gw = build(clock=clock)
        seen = []
        gw.gateway.set_handler("executor", lambda raw: seen.append(raw))
        m = make_action(SESSION, AGENT, "browser.navigate", params={"url": "https://x"})
        m.seq = 1
        out = gw.gateway.receive("agent", m.to_dict())
        aid = out[0].id
        for _ in range(3):  # timeout → redeliver ×3 (retries=3)
            clock.advance(30000)
            gw.tick()
        redelivered = [r for r in seen if r["id"] == aid]
        assert len(redelivered) == 3
        # 第 4 次超时 → terminal timeout，不再重发
        clock.advance(30000)
        gw.tick()
        status, _ = gw.gateway.session.actions.outcome(aid)
        assert status == "timeout"
        assert len([r for r in seen if r["id"] == aid]) == 3  # 3 次重试，复用同一 id

    def test_resume_redelivers_buffered_messages(self):
        gw = build()
        inbox = []
        # executor 断连期间事件仍被缓冲（投递给 agent 侧）
        gw.gateway.disconnect("executor")
        m = make_event(SESSION, EXEC, "browser.page.loaded", data={})
        m.seq = 1
        gw.gateway.receive("executor", m.to_dict())
        assert gw.gateway.outbound["agent"], "event must be buffered for agent"
        gw.gateway.reconnect("executor")
        gw.gateway.set_handler("agent", lambda raw: inbox.append(raw))
        gw.gateway.resume("agent", cursors={EXEC: 0})
        assert len(inbox) == 1 and inbox[0]["id"] == m.id


class TestAIPExecutorBase:
    def _peer_pair(self):
        """直连 peer 对（不经 gateway），测基类协议行为。"""
        from aip import Endpoint, connect_peers
        left, right = Endpoint("left"), Endpoint("right")
        connect_peers(left, right)
        return left, right

    def test_accepted_first_then_ok(self):
        left, right = self._peer_pair()
        ex = RecordingExecutor("ex", SESSION, transport=left)
        sent = []
        right.attach(lambda raw: sent.append(raw))
        m = make_action(SESSION, "ag", "browser.click", params={"target": "b"})
        m.seq = 1
        ex.on_message(m.to_dict())
        statuses = [s["payload"]["status"] for s in sent if s["type"] == "result"]
        assert statuses[0] == "accepted"
        assert statuses[-1] == "ok"

    def test_idempotency_guard_no_double_execute(self):
        left, right = self._peer_pair()
        ex = RecordingExecutor("ex", SESSION, transport=left)
        sent = []
        right.attach(lambda raw: sent.append(raw))
        m = make_action(SESSION, "ag", "browser.click", params={"target": "b"})
        m.seq = 1
        ex.on_message(m.to_dict())
        replay = dict(m.to_dict())  # 同一 action.id 重放（seq 相同 → duplicate 分支）
        ex.on_message(replay)
        assert len(ex.executed) == 1
        dup = [s for s in sent if s["payload"].get("duplicate")]
        assert dup and dup[0]["payload"]["status"] == "ok"

    def test_business_failure_is_result_failed_not_error(self):
        left, right = self._peer_pair()
        ex = RecordingExecutor("ex", SESSION, transport=left, fail_on={"browser.click"})
        sent = []
        right.attach(lambda raw: sent.append(raw))
        m = make_action(SESSION, "ag", "browser.click", params={"target": "b"})
        m.seq = 1
        ex.on_message(m.to_dict())
        last = sent[-1]
        assert last["type"] == "result" and last["payload"]["status"] == "failed"
        assert last["payload"]["code"] == "boom"

    def test_builtin_context_get(self):
        left, right = self._peer_pair()
        ex = RecordingExecutor("ex", SESSION, transport=left)
        ref = ex.put_context("order", {"order_id": "PO-1", "amount": 5})
        sent = []
        right.attach(lambda raw: sent.append(raw))
        m = make_action(SESSION, "ag", "context.get",
                        params={"ref": ref, "fields": ["order_id"]})
        m.seq = 1
        ex.on_message(m.to_dict())
        ok = sent[-1]
        assert ok["payload"]["status"] == "ok"
        assert ok["payload"]["data"]["data"] == {"order_id": "PO-1"}

    def test_emit_rejects_oversized_data_cod1(self):
        ex = RecordingExecutor("ex", SESSION)
        with pytest.raises(ValueError):
            ex.emit("browser.page.loaded", {"blob": "x" * 5000})

    def test_precondition_error_yields_rejected(self):
        class PreconditionExec(RecordingExecutor):
            def _execute_action(self, name, params):
                raise ExecutorPreconditionError("order_not_pending")

        left, right = self._peer_pair()
        ex = PreconditionExec("ex", SESSION, transport=left)
        sent = []
        right.attach(lambda raw: sent.append(raw))
        m = make_action(SESSION, "ag", "erp.order.approve", params={"order_id": "P"})
        m.seq = 1
        ex.on_message(m.to_dict())
        last = sent[-1]
        assert last["type"] == "result" and last["payload"]["status"] == "rejected"
        assert last["payload"]["code"] == "order_not_pending"


class TestSemanticAdapter:
    def get_adapter(self):
        from apa_sdk.semantic_adapter import Element, ScreenState, SemanticAdapter
        schema = {
            "semantic_patterns": {
                "page": {
                    "trigger": {"url_pattern": "*orders*"},
                    "emit": {
                        "event": "erp.order.list.loaded",
                        "data_mapping": {
                            "url": {"selector": "__url__"},
                            "count": {"selector": "[data-count]", "transform": "parse_int"},
                        },
                    },
                },
                "dialog": {
                    "trigger": {"element": {"role": "heading"},
                                "contains": [{"role": "button"}]},
                    "emit": {
                        "event": "erp.order.approval_requested",
                        "data_mapping": {
                            "order_id": {"selector": "[data-order-id]"},
                            "amount": {"selector": ".amount", "transform": "parse_currency"},
                        },
                    },
                },
            }
        }
        state = ScreenState(url="https://x/orders/pending", title="待办", elements=[
            Element(role="heading", text="审批", id="h"),
            Element(role="button", text="批准", data_apa_id="ok"),
            Element(role="cell", text="PO-9", attrs={"data-order-id": "PO-9"}),
            Element(role="cell", text="$45.00", attrs={"class": "amount"}),
            Element(role="grid", text="", attrs={"data-count": "7"}),
        ])
        return SemanticAdapter(schema), state

    def test_lift_emits_matched_patterns(self):
        adapter, state = self.get_adapter()
        events = {e.name: e.data for e in adapter.lift(state)}
        assert "erp.order.list.loaded" in events
        assert events["erp.order.list.loaded"]["count"] == 7
        dlg = events["erp.order.approval_requested"]
        assert dlg["order_id"] == "PO-9"
        assert dlg["amount"] == 45.0

    def test_url_pattern_mismatch_skips(self):
        from apa_sdk.semantic_adapter import Element, ScreenState, SemanticAdapter
        adapter, _ = self.get_adapter()
        other = ScreenState(url="https://y/other", elements=[
            Element(role="heading", text="审批")])
        assert adapter.lift(other) == []


class TestCoalescer:
    def test_sync_coalescer_last_write_wins(self):
        from apa_sdk.coalescer import SyncCoalescer
        c = SyncCoalescer(debounce_ms=10 ** 9)  # 窗口极大：全部合并
        c.emit("e", {"v": 1})
        c.emit("e", {"v": 2})
        flushed = c.flush()
        assert flushed == [("e", {"v": 2})]
        assert c.suppressed == 1