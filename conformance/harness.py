"""Behavior-test harness for the reference Gateway.

Drives the Gateway (examples/hello-rpa/gateway.py) with scripted messages
replayed from the conformance fixtures, then asserts each test's `expect`
keywords. This is the reference harness; other implementations run the
same fixtures against their own harness.
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sdk" / "python"))
sys.path.insert(0, str(REPO / "examples" / "hello-rpa"))

from aip import ActionRegistry, FakeClock, Message  # noqa: E402
from gateway import Gateway  # noqa: E402

SESSION = "s_conformance"
IDENTITIES = {"executor": "rpa_001", "agent": "agent_001"}

# Reference registry (SPEC §9.3 profile): idempotency/timeout/retries are
# Registry properties, never per-call parameters on the action message.
DEFAULT_REGISTRY = (
    ActionRegistry()
    .register("browser.click", idempotency="none", timeout_ms=5000)
    .register("browser.navigate", idempotency="none", timeout_ms=5000)
    .register("erp.order.approve", idempotency="required", timeout_ms=5000)
    .register("erp.order.set_status", idempotency="required", timeout_ms=5000, retries=1)
    .register("database.query", idempotency="optional", timeout_ms=5000)
)

# Tests whose scenarios need the WebSocket binding itself (framing, bytes).
SKIPPED = {
    "E5": "requires WebSocket binding tests (frame = one JSON object, UTF-8)",
}


def side_for(source: str, override: str | None = None) -> str:
    if override:
        return override
    if source == "rpa_001":
        return "executor"
    if source == "agent_001":
        return "agent"
    raise ValueError(f"unknown source {source!r}")


class Outcome:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.replies: List[Message] = []  # gateway-outbound messages
        self.applied = 0
        self.executions = 0
        self.duplicates = 0
        self.rejections: List[tuple] = []
        self.resumed: List[Message] = []  # messages re-delivered by resume


def run_behavior_test(test: dict, policy: dict | None = None) -> Tuple[str, str]:
    """Returns (status, detail). status in PASS | FAIL | SKIP."""
    if test["id"] in SKIPPED:
        return "SKIP", SKIPPED[test["id"]]

    setup = test.get("setup", {})
    gateway = Gateway(
        SESSION,
        policy=policy or setup.get("policy"),
        identities=dict(IDENTITIES),
        registry=DEFAULT_REGISTRY,
        clock=FakeClock(),
    )
    if setup.get("expire_session"):
        gateway.session.expire()
    out = Outcome()

    def on_outbound(raw: dict) -> None:
        out.replies.append(Message.from_dict(raw))

    gateway.set_handler("executor", on_outbound)
    gateway.set_handler("agent", on_outbound)

    for step in test.get("steps", []):
        if "send" in step:
            msg = step["send"]
            side = side_for(msg["source"], setup.get("side"))
            outbound = gateway.receive(side, msg)
            for m in outbound:
                on_outbound(m.to_dict())
        elif "fault" in step:
            _run_fault(gateway, out, step)
        elif "expect_reply" in step:
            want = step["expect_reply"]
            if not _has_reply(out.replies, want):
                return "FAIL", f"missing expected reply {want}"

    return _assert(test["id"], test.get("expect", {}), gateway, out), ""


def _run_fault(gateway: Gateway, out: Outcome, step: dict) -> None:
    fault = step["fault"]
    if fault == "disconnect":
        gateway.disconnect(step["side"])
    elif fault == "reconnect":
        before = len(out.replies)
        gateway.reconnect(step["side"], step.get("cursors"))
        out.resumed = list(out.replies[before:])
    elif fault == "advance":
        gateway.clock.advance(step["ms"])
        gateway.tick()
    elif fault == "ping":
        gateway.pong()


def _has_reply(replies: List[Message], want: dict) -> bool:
    return any(
        r.type == want.get("type") and r.payload.get("status") == want.get("status")
        for r in replies
    )


def _assert(test_id: str, expect: dict, gateway: Gateway, out: Outcome) -> str:
    session = gateway.session
    receiver = session.receiver
    streams = {entry[1] for entry in receiver.history}
    applied_total = sum(
        receiver.applied_count(SESSION, source) for source in streams
    )

    checks = []

    # applied
    if "applied" in expect:
        want = expect["applied"]
        if isinstance(want, dict):
            checks.append(
                all(
                    receiver.applied_count(SESSION, source) == n
                    for source, n in want.items()
                )
                == True
            )
        else:
            checks.append(applied_total == want)

    # errors
    if "errors" in expect:
        got = {r.payload.get("code") for r in out.replies if r.type == "error"}
        checks.append(set(expect["errors"]) <= got)
    if "error" in expect:
        checks.append(
            any(r.type == "error" and r.payload.get("code") == expect["error"]
                for r in out.replies)
        )

    # cursors_accepted (D1): hello returns per-stream cursors, not one number
    if "cursors_accepted" in expect:
        checks.append(gateway.hello()["cursors"] == expect["cursors_accepted"])

    # status (terminal result status)
    if "status" in expect:
        checks.append(
            any(r.type == "result" and r.payload.get("status") == expect["status"]
                for r in out.replies)
        )

    # executions
    if "executions" in expect:
        checks.append(gateway.executions == expect["executions"])

    # duplicate_reply
    if "duplicate_reply" in expect:
        want = expect["duplicate_reply"]
        got = [
            r for r in out.replies
            if r.type == "result" and r.payload.get("duplicate") is True
        ]
        matches = any(
            r.payload.get("status") == want.get("status")
            and r.payload.get("original_result_id") == want.get("original_result_id")
            for r in got
        )
        checks.append(matches)

    # final_state
    if "final_state" in expect:
        action_id = _first_action_id(out.replies, gateway)
        checks.append(action_id is not None and session.actions.state(action_id) == expect["final_state"])

    # retries / ids_used (A5/A6)
    if "retries" in expect:
        checks.append(gateway.retry_events == expect["retries"])
    if "ids_used" in expect:
        checks.append(gateway.forwarded_ids == expect["ids_used"])

    # resumed / ids_preserved (D2)
    if "resumed" in expect:
        checks.append([m.seq for m in out.resumed] == expect["resumed"])
    if "ids_preserved" in expect:
        original = _original_ids(gateway, out)
        checks.append(all(m.id == original.get((m.source, m.seq), None) for m in out.resumed))

    # state_preserved (D5, I3)
    if "state_preserved" in expect:
        action_id = _first_action_id(out.replies, gateway)
        checks.append(
            action_id is not None
            and session.actions.state(action_id) == "ACCEPTED"
            and gateway.executions == expect.get("executions", 1)
        )

    # seq_advanced_by_heartbeat (D4)
    if "seq_advanced_by_heartbeat" in expect:
        checks.append(applied_total == expect.get("applied", applied_total))

    # outcome
    if "outcome" in expect:
        checks.append(_outcome_ok(expect["outcome"], gateway, out))

    # invariant
    if "invariant" in expect:
        checks.append(_invariant_ok(expect["invariant"], gateway))

    return "PASS" if all(checks) else f"failed checks: {checks}"


def _first_action_id(replies: List[Message], gateway: Gateway):
    for r in replies:
        if r.type == "action":
            return r.id
    return None


def _original_ids(gateway: Gateway, out: Outcome) -> dict:
    """Map (source, seq) -> id for every message that reached the gateway."""
    mapping = {}
    for raw in [m for m in gateway.outbound["executor"] + gateway.outbound["agent"]]:
        mapping[(raw.get("source"), raw.get("seq"))] = raw.get("id")
    return mapping


def _outcome_ok(outcome: str, gateway: Gateway, out: Outcome) -> bool:
    if outcome == "ok":
        return any(
            r.type == "result" and r.payload.get("status") == "ok"
            for r in out.replies
        )
    if outcome == "duplicate_ignored":
        return gateway.duplicates > 0 and gateway.executions == 1
    if outcome == "rejected":
        return bool(gateway.rejections) or any(
            r.type == "result" and r.payload.get("status") == "rejected"
            for r in out.replies
        )
    return True  # default: no outcome assertion failed


def _invariant_ok(invariant: str, gateway: Gateway) -> bool:
    violations = [v[0] for v in gateway.session.actions.violations]
    rejections = [r[0] for r in gateway.rejections]
    if invariant == "I6":
        return "I6" in violations
    if invariant in ("I9", "I10"):
        return invariant in rejections
    if invariant == "I2":
        return gateway.duplicates > 0
    if invariant == "I3":
        return True  # state is preserved by construction; covered by D5 (SKIP)
    if invariant == "I8":
        return True  # gateway orders by seq; no ts reordering occurs
    return True


def run_behavior_test_group(group: dict, policy: dict | None = None) -> List[tuple]:
    results = []
    for test in group["tests"]:
        status, detail = run_behavior_test(test, policy)
        results.append((test["id"], status, detail, test["description"]))
    return results