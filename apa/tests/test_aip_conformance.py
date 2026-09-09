"""AIP 内核一致性：conformance 行为夹具跑 APA APAGateway（C 阶段）。

对应 repo-root conformance/harness.py（reference Gateway 版）；
断言语义逐项对齐，surface 差异见内联注释：
  · registry：APA ActionRegistry（SDK 版缺 params/schema，不可用）
  · policy：fixture dict → PolicyConfig 翻译
  · retries：读 retry_scheduler.retry_events
  · outbound：APA 存 dict（to_dict 后），_original_ids 照读
"""
import json
from pathlib import Path

import pytest
from aip import FakeClock, Message

from apa_core.gateway import APAGateway
from apa_core.policy import PolicyConfig
from apa_core.registry import ActionRegistry

REPO = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO / "conformance" / "tests"
SESSION = "s_conformance"
IDENTITIES = {"executor": "rpa_001", "agent": "agent_001"}

SKIPPED = {
    "E5": "requires WebSocket binding tests (frame = one JSON object)",
}


def _registry():
    r = ActionRegistry()
    for name, idem, to, ret in [
        ("browser.click", "none", 5000, 0),
        ("browser.navigate", "none", 5000, 0),
        ("erp.order.approve", "required", 5000, 0),
        ("erp.order.set_status", "required", 5000, 1),
        ("database.query", "optional", 5000, 0),
    ]:
        r._register(name, {"idempotency": idem, "timeout_ms": to,
                           "retries": ret})
    return r


def _side(source, override=None):
    if override:
        return override
    if source == "rpa_001":
        return "executor"
    if source == "agent_001":
        return "agent"
    raise ValueError(f"unknown source {source!r}")


class _Out:
    def __init__(self):
        self.replies = []
        self.resumed = []


def _run_one(test, policy=None):
    if test["id"] in SKIPPED:
        return "SKIP", SKIPPED[test["id"]]
    setup = test.get("setup", {})
    pol = dict(policy or setup.get("policy") or {})
    gw = APAGateway(
        SESSION, registry=_registry(),
        policy=PolicyConfig(**pol),
        identities=dict(IDENTITIES), clock=FakeClock(),
    )
    if setup.get("expire_session"):
        gw.session.expire()
    out = _Out()
    gw.set_handler("executor", lambda raw: out.replies.append(
        Message.from_dict(raw)))
    gw.set_handler("agent", lambda raw: out.replies.append(
        Message.from_dict(raw)))
    for step in test.get("steps", []):
        if "send" in step:
            msg = step["send"]
            for m in gw.receive(_side(msg["source"], setup.get("side")),
                                msg):
                out.replies.append(m)
        elif "fault" in step:
            f = step["fault"]
            if f == "disconnect":
                gw.disconnect(step["side"])
            elif f == "reconnect":
                before = len(out.replies)
                gw.reconnect(step["side"], step.get("cursors"))
                out.resumed = list(out.replies[before:])
            elif f == "advance":
                gw.clock.advance(step["ms"])
                gw.tick()
            elif f == "ping":
                gw.pong()
        elif "expect_reply" in step:
            want = step["expect_reply"]
            if not any(r.type == want.get("type") and
                       r.payload.get("status") == want.get("status")
                       for r in out.replies):
                return "FAIL", f"missing expected reply {want}"
    return _assert(test["id"], test.get("expect", {}), gw, out), ""


def _assert(test_id, expect, gw, out):
    session = gw.session
    receiver = session.receiver
    streams = {entry[1] for entry in receiver.history}
    applied_total = sum(
        receiver.applied_count(SESSION, source) for source in streams)
    checks = []
    if "applied" in expect:
        want = expect["applied"]
        if isinstance(want, dict):
            checks.append(all(
                receiver.applied_count(SESSION, source) == n
                for source, n in want.items()))
        else:
            checks.append(applied_total == want)
    if "errors" in expect:
        got = {r.payload.get("code") for r in out.replies
               if r.type == "error"}
        checks.append(set(expect["errors"]) <= got)
    if "error" in expect:
        checks.append(any(
            r.type == "error" and r.payload.get("code") == expect["error"]
            for r in out.replies))
    if "cursors_accepted" in expect:
        checks.append(gw.hello()["cursors"] == expect["cursors_accepted"])
    if "status" in expect:
        checks.append(any(
            r.type == "result" and r.payload.get("status") == expect["status"]
            for r in out.replies))
    if "executions" in expect:
        checks.append(gw.executions == expect["executions"])
    if "duplicate_reply" in expect:
        want = expect["duplicate_reply"]
        checks.append(any(
            r.type == "result" and r.payload.get("duplicate") is True
            and r.payload.get("status") == want.get("status")
            and r.payload.get("original_result_id") ==
            want.get("original_result_id")
            for r in out.replies))
    if "final_state" in expect:
        aid = next((r.id for r in out.replies if r.type == "action"), None)
        checks.append(aid is not None and
                      session.actions.state(aid) == expect["final_state"])
    if "retries" in expect:
        checks.append(gw.retry_scheduler.retry_events == expect["retries"])
    if "ids_used" in expect:
        checks.append(gw.forwarded_ids == expect["ids_used"])
    if "resumed" in expect:
        checks.append([m.seq for m in out.resumed] == expect["resumed"])
    if "ids_preserved" in expect:
        mapping = {}
        for raw in gw.outbound["executor"] + gw.outbound["agent"]:
            mapping[(raw.get("source"), raw.get("seq"))] = raw.get("id")
        checks.append(all(
            m.id == mapping.get((m.source, m.seq)) for m in out.resumed))
    if "state_preserved" in expect:
        aid = next((r.id for r in out.replies if r.type == "action"), None)
        checks.append(aid is not None and
                      session.actions.state(aid) == "ACCEPTED" and
                      gw.executions == expect.get("executions", 1))
    if "outcome" in expect:
        o = expect["outcome"]
        if o == "ok":
            checks.append(any(
                r.type == "result" and r.payload.get("status") == "ok"
                for r in out.replies))
        elif o == "duplicate_ignored":
            checks.append(gw.duplicates > 0 and gw.executions == 1)
        elif o == "rejected":
            checks.append(bool(gw.rejections) or any(
                r.type == "result" and r.payload.get("status") == "rejected"
                for r in out.replies))
    if "invariant" in expect:
        inv = expect["invariant"]
        violations = [v[0] for v in session.actions.violations]
        rejections = [r[0] for r in gw.rejections]
        if inv == "I6":
            checks.append("I6" in violations)
        elif inv in ("I9", "I10"):
            checks.append(inv in rejections)
        elif inv == "I2":
            checks.append(gw.duplicates > 0)
        else:
            checks.append(True)
    return "PASS" if all(checks) else f"failed checks: {checks}"


def _all_tests():
    cases = []
    for path in sorted(TESTS_DIR.glob("*.json")):
        group = json.loads(path.read_text(encoding="utf-8"))
        for t in group["tests"]:
            if t.get("kind") == "behavior":
                cases.append(pytest.param(t, id=t["id"]))
    return cases


@pytest.mark.parametrize("test", _all_tests())
def test_aip_kernel_against_apa_gateway(test):
    status, detail = _run_one(test)
    assert status in ("PASS", "SKIP"), f"{test['id']}: {status} {detail}"
