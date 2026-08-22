#!/usr/bin/env python3
"""APA-Profile 合规测试套件（设计文档 §16.1：≥10 个用例覆盖 CoD 规则）。

覆盖：
  CoD-1  事件 data ≤ 4KB
  CoD-2  context.get 禁止 fields:["*"]
  CoD-3  ContextStore 由 Executor 持有（ref 归属校验）
  §4.1   事件命名空间 / 命令式事件名禁止 / 业务域事件只由 Executor 发出
  C3     idempotency/risk 只来自 Registry
  C4     凭据不进入 payload
  C5/C7  上下文引用传递 / 决策引擎无状态
  I9     source 绑定
  S1-S5  序列检查
  A3/A4  幂等性（重试复用同一 action.id）
  §4.3   human.task → SUSPENDED → completed → RUNNING
  §9.2   L3+ 风险策略 → REQUIRE_HUMAN
  §10.1  session.complete → COMPLETED

用法：python3 conformance/run.py   （退出码 0 = 全部通过）
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APA_ROOT = HERE.parent
sys.path.insert(0, str(APA_ROOT / "packages" / "apa-core"))
sys.path.insert(0, str(APA_ROOT / "packages" / "apa-sdk-python"))
sys.path.insert(0, str(APA_ROOT))

from aip import FakeClock, make_action, make_event

from apa_core.context import APAContextStore, ContextRefError
from apa_core.embedded import EmbeddedGateway
from apa_core.policy import PolicyConfig
from apa_core.registry import ActionRegistry, load_registries
from apa_core.rules import RuleBasedAgent
from apa_sdk.testing import MockGateway

SESSION = "s_conf_001"
EXEC = "exec_001"
AGENT = "agent_001"


def build(registry=None, policy=None, clock=None):
    global _seq
    _seq = {EXEC: 0, AGENT: 0}  # 每个用例独立的序列计数
    gw = EmbeddedGateway(
        SESSION,
        registry=registry or load_registries(
            APA_ROOT / "registries" / "core.yaml",
            APA_ROOT / "registries" / "browser.yaml",
            APA_ROOT / "registries" / "desktop.yaml",
            APA_ROOT / "registries" / "api.yaml"),
        policy=policy or PolicyConfig(),
        identities={"executor": EXEC, "agent": AGENT},
        clock=clock,
    )
    gw.run()  # Session 进入 RUNNING（§10.1）
    return gw


_seq = {EXEC: 0, AGENT: 0}


def next_seq(source: str) -> int:
    if source not in _seq:
        _seq[source] = 0
    _seq[source] += 1
    return _seq[source]


def send_event(gw, name, data=None, seq=None):
    msg = make_event(SESSION, EXEC, name, data=data)
    msg.seq = seq if seq is not None else next_seq(EXEC)
    return gw.gateway.receive("executor", msg.to_dict())


def send_action(gw, name, params=None, source=AGENT, seq=None, payload_extra=None):
    msg = make_action(SESSION, source, name, params=params)
    if payload_extra:
        msg.payload.update(payload_extra)
    msg.seq = seq if seq is not None else next_seq(source)
    return gw.gateway.receive("agent", msg.to_dict())


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# --- CoD-1: 事件 data ≤ 4KB ---------------------------------------------------
@case
def cod1_event_data_limit():
    gw = build()
    big = {"blob": "x" * 5000}
    out = send_event(gw, "browser.page.loaded", {"url": "https://x", "context": "ctx_s_conf_001_p1"})
    assert out and out[0].type == "event", "normal event should pass"
    out = send_event(gw, "browser.page.loaded", big)
    assert out and out[0].type == "error", "oversized event must be INVALID_MESSAGE"
    assert out[0].payload["code"] == "INVALID_MESSAGE"


# --- CoD-2: context.get 禁止 fields:["*"] --------------------------------------
@case
def cod2_wildcard_forbidden():
    gw = build()
    out = send_action(gw, "context.get", {"ref": f"ctx_{SESSION}_x", "fields": ["*"]})
    assert out[0].payload.get("status") == "rejected", "wildcard must be rejected"
    assert out[0].payload.get("code") == "invalid_params"


@case
def cod2_wildcard_forbidden_at_store():
    store = APAContextStore(SESSION)
    store.put(f"ctx_{SESSION}_a", {"k": 1})
    data, err = store.get(f"ctx_{SESSION}_a", ["*"])
    assert data is None and err == "context.wildcard_forbidden"


# --- CoD-3/ref 归属：跨 Session 引用拒绝 ----------------------------------------
@case
def ref_belongs_to_session():
    store = APAContextStore(SESSION)
    try:
        store.put("ctx_other_session_x", {"k": 1})
        raise AssertionError("cross-session ref must be rejected")
    except ContextRefError:
        pass


# --- §4.1: 事件命名空间 --------------------------------------------------------
@case
def event_namespace_domain_whitelist():
    gw = build()
    out = send_event(gw, "galaxy.planet.exploded", {})
    assert out[0].type == "error" and out[0].payload["code"] == "INVALID_MESSAGE"


@case
def event_namespace_no_imperatives():
    gw = build()
    for bad in ("please.click.button", "do.approve.order", "browser.do.click"):
        out = send_event(gw, bad, {})
        assert out[0].type == "error", f"{bad} must be rejected"


@case
def business_events_only_from_executor():
    gw = build()
    # agent 侧发业务域事件 → 拒绝（决策引擎不发业务事实）
    msg = make_event(SESSION, AGENT, "erp.order.approval_requested", data={})
    msg.seq = next_seq(AGENT)
    out = gw.gateway.receive("agent", msg.to_dict())
    assert out[0].type == "error" and out[0].payload["code"] == "INVALID_MESSAGE"


# --- C3: idempotency/risk 只能来自 Registry -------------------------------------
@case
def c3_no_idempotency_in_action():
    gw = build()
    out = send_action(gw, "erp.order.approve",
                      {"order_id": "PO-1"}, payload_extra={"idempotency": "required"})
    assert out[0].payload.get("status") == "rejected"
    assert "C3" in (out[0].payload.get("message") or "")


@case
def c3_registry_is_authority():
    reg = load_registries(APA_ROOT / "registries" / "api.yaml")
    entry = reg.get("erp.order.approve")
    assert entry.idempotency == "required" and entry.risk == "L2"
    # 同一 action.id 重放 → 返回存储结果，不重复执行（A3/A4）
    gw = build()
    out1 = send_action(gw, "erp.order.approve", {"order_id": "PO-1"}, seq=1)
    assert out1[0].type == "action"  # 转发 executor
    # executor 回 ok
    from aip import make_result
    res = make_result(SESSION, EXEC, "ok", in_reply_to=out1[0].id)
    res.seq = next_seq(EXEC)
    gw.gateway.receive("executor", res.to_dict())
    # 重放同一 action.id（seq 不同，模拟重试）
    replay = make_action(SESSION, AGENT, "erp.order.approve",
                         params={"order_id": "PO-1"}, id=out1[0].id, seq=2)
    out2 = gw.gateway.receive("agent", replay.to_dict())
    assert out2[0].type == "result" and out2[0].payload.get("duplicate") is True
    assert out2[0].payload["status"] == "ok"


# --- C4: 凭据扫描 --------------------------------------------------------------
@case
def c4_credential_scan():
    gw = build()
    for params in (
        {"url": "https://x", "headers": {"Authorization": "Bearer abc123"}},
        {"target": "pw", "value": "password=hunter2"},
    ):
        name = "api.http.post" if "url" in params else "browser.input"
        out = send_action(gw, name, params)
        assert out[0].payload.get("status") == "rejected", params
        assert out[0].payload.get("code") == "credential_in_payload"


# --- I9: source 绑定 -----------------------------------------------------------
@case
def i9_source_binding():
    gw = build()
    msg = make_action(SESSION, "impostor", "session.complete", params={})
    out = gw.gateway.receive("agent", msg.to_dict())
    assert out[0].type == "error" and out[0].payload["code"] == "UNAUTHORIZED"


# --- S1-S5: 序列检查 -------------------------------------------------------------
@case
def sequence_gap_rejected():
    gw = build()
    out = send_event(gw, "browser.page.loaded", {}, seq=5)  # 首条 seq 必须 1
    assert out[0].type == "error" and out[0].payload["code"] == "SEQ_OUT_OF_ORDER"


# --- 未注册动作 / Schema 校验 ------------------------------------------------------
@case
def unregistered_action_rejected():
    gw = build()
    out = send_action(gw, "bank.transfer.now", {"amount": 1})
    assert out[0].payload.get("status") == "rejected"
    assert out[0].payload.get("code") == "action_not_registered"


@case
def invalid_params_rejected():
    gw = build()
    out = send_action(gw, "browser.navigate", {"nope": True})
    assert out[0].payload.get("status") == "rejected"
    assert out[0].payload.get("code") == "invalid_params"


# --- §9.2/§4.3: 高风险 → REQUIRE_HUMAN → SUSPENDED → 恢复 -------------------------
@case
def l3_risk_requires_human_and_suspends():
    gw = build()
    assert gw.gateway.sm.state == "RUNNING"
    out = send_action(gw, "desktop.file.delete", {"path": "/tmp/x"})
    assert out[0].payload.get("status") == "rejected"
    assert out[0].payload.get("code") == "requires_human_approval"
    assert gw.gateway.sm.state == "SUSPENDED"
    # 人工完成 → executor 发 human.task.completed → RUNNING
    msg = make_event(SESSION, EXEC, "human.task.completed",
                     data={"task_id": gw.gateway.sm.record.human_tasks[0], "outcome": "retry"})
    msg.seq = next_seq(EXEC)
    out = gw.gateway.receive("executor", msg.to_dict())
    assert gw.gateway.sm.state == "RUNNING"


@case
def suspended_blocks_business_actions():
    gw = build()
    send_action(gw, "desktop.file.delete", {"path": "/tmp/x"})  # → SUSPENDED
    out = send_action(gw, "erp.order.approve", {"order_id": "PO-1"})
    assert out[0].payload.get("status") == "rejected"
    assert out[0].payload.get("code") == "session_state_mismatch"


# --- §8.3: 幂等动作超时重试复用同一 action.id ---------------------------------------
@case
def retry_scheduler_reuses_action_id():
    clock = FakeClock(start_ms=1000)
    gw = build(clock=clock)
    seen = []
    gw.gateway.set_handler("executor", lambda raw: seen.append(raw))
    out = send_action(gw, "browser.navigate", {"url": "https://x"})  # retries=3
    action_id = out[0].id
    first = list(seen)
    clock.advance(30000)
    gw.tick()
    assert len(seen) == len(first) + 1, "timeout must trigger redelivery"
    assert seen[-1]["id"] == action_id, "retry must reuse the same action.id"


@case
def timeout_marks_terminal_when_retries_exhausted():
    clock = FakeClock(start_ms=1000)
    gw = build(clock=clock)
    out = send_action(gw, "browser.scroll", {"direction": "down"})  # retries=0
    action_id = out[0].id
    clock.advance(3000)
    gw.tick()
    status, _ = gw.gateway.session.actions.outcome(action_id)
    assert status == "timeout"


# --- §10.1: session.complete → COMPLETED -----------------------------------------
@case
def session_complete_transitions_state():
    gw = build()
    out = send_action(gw, "session.complete", {"outcome": "success"})
    assert out[0].payload.get("status") == "ok"
    assert gw.gateway.sm.state == "COMPLETED"


# --- C5/C7: 事件只带引用；决策引擎可经 context.get 取字段 ------------------------------
@case
def context_reference_roundtrip():
    from apa_executors.browser_executor import BrowserExecutor  # noqa: F401  (依赖自检)
    from apa_sdk.testing import MockGateway as MG  # noqa: F401
    store = APAContextStore(SESSION)
    ref = store.make_ref(SESSION, "order")
    store.put(ref, {"order_id": "PO-5678", "amount": 45000.0, "secret_field": "x"},
              allowed_fields=["order_id", "amount"])
    data, err = store.get(ref, ["amount"], principal="dsh_agent_001")
    assert err is None and data == {"amount": 45000.0}
    # ACL 外字段取不到
    data, err = store.get(ref, ["secret_field"], principal="dsh_agent_001")
    assert data == {}


def main() -> int:
    passed, failed = [], []
    for fn in CASES:
        try:
            fn()
            passed.append(fn.__name__)
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed.append((fn.__name__, str(e)))
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed.append((fn.__name__, repr(e)))
            print(f"  ERROR {fn.__name__}: {e!r}")
    print(f"\nAPA-Profile conformance: {len(passed)}/{len(CASES)} passed"
          + ("" if not failed else f", {len(failed)} FAILED"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())