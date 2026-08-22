#!/usr/bin/env python3
"""APA po-approval — Process Mode 验收场景（设计文档 §10.2 模式 B / §16.2 v0.3）。

流程：审批事件 → CoD 取订单字段 → 金额分流（批准/驳回）→ 通知 → 完成。
执行侧为 CompositeExecutor（api/erp 域 + 内置 context.*），ERP 为本地 mock。

    python run.py            # 小额订单 → 批准
    python run.py --over     # 大额订单 → 驳回
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APA_ROOT = HERE.parent.parent

for p in ("apa-core", "apa-sdk-python", "apa-executors"):
    sys.path.insert(0, str(APA_ROOT / "packages" / p))
sys.path.insert(0, str(APA_ROOT / "sdk" / "python"))

from aip import AIPPeer

from apa_core.embedded import EmbeddedGateway
from apa_core.mock_erp import MockERP
from apa_core.policy import PolicyConfig
from apa_core.process import ProcessEngine, load_process
from apa_core.registry import load_registries

from apa_executors.api_executor import APIExecutor
from apa_sdk.composite import CompositeExecutor

SESSION = "s_po_001"



def run(over_budget: bool) -> int:
    registries = load_registries(
        APA_ROOT / "registries" / "core.yaml",
        APA_ROOT / "registries" / "desktop.yaml",
        APA_ROOT / "registries" / "document.yaml",
        APA_ROOT / "registries" / "api.yaml")
    gateway = EmbeddedGateway(
        SESSION,
        registry=registries,
        policy=PolicyConfig(),
        identities={"executor": ["bot_01"], "agent": "proc_01"},
        process_id="po_auto_approval",
    )
    erp = MockERP(seed_orders=[{"id": "PO-9012", "status": "pending"}])
    ERP_PORT = erp.start()

    router = CompositeExecutor("bot_01", SESSION)
    api_mod = APIExecutor("bot_01", SESSION,
                          base_url=f"http://127.0.0.1:{ERP_PORT}")
    router.register(("api", "erp"), api_mod)

    # 预置订单上下文（CoD：事件只带引用）
    amount = 350000.0 if over_budget else 45000.0
    order_ref = router.context_store.make_ref(SESSION, "order")
    router.context_store.put(order_ref, {
        "order_id": "PO-9012", "amount": amount, "vendor": "示例供应商C"})

    proc_def = load_process(str(HERE / "process.yaml"))
    # agent 侧协议身份（发送与接收共用同一 peer，transport 由 attach 接线）
    agent_obj = _Passthrough(lambda raw: None)
    peer = agent_obj.peer

    # --- 同步 send-and-wait 驱动（内嵌模式：结果经重入即时回流） -----------------
    pending: dict = {}

    def agent_inbox(raw: dict) -> None:
        cls, msg = peer.handle(raw)
        if cls != "accept":
            return
        if msg.type == "event":
            payload = msg.payload
            engine.on_trigger(payload.get("name", ""),
                              payload.get("data") or {})
        elif msg.type == "result" and msg.in_reply_to in pending:
            pending[msg.in_reply_to] = msg.payload
    agent_obj.on_message = agent_inbox

    def send_and_wait(name: str, params: dict):
        act = peer.build_action(name, params=params or None)
        pending[act.id] = None
        peer.send(act)
        payload = pending.pop(act.id)
        if payload is None:
            return False, {"code": "no_result"}
        status = payload.get("status")
        ok = status == "ok"
        return ok, (payload.get("data") if ok else {"code": payload.get("code")})

    engine = ProcessEngine(
        proc_def, send_and_wait,
        complete_fn=lambda outcome: (
            peer.build_action("session.complete",
                              params={"outcome": "success"
                                      if outcome == "success" else outcome})
            if outcome in ("success", "failure") else None),
    )
    # complete_fn 只构造；发送走 peer（避免在网关拦截分支内再触发 deliver 重入）
    def _complete(outcome: str) -> None:
        act = peer.build_action("session.complete",
                                params={"outcome": "success"
                                        if outcome == "success" else outcome})
        peer.send(act)

    engine.complete_fn = _complete

    def agent_inbox(raw: dict) -> None:
        cls, msg = peer.handle(raw)
        if cls != "accept":
            return
        if msg.type == "event":
            payload = msg.payload
            engine.on_trigger(payload.get("name", ""),
                              payload.get("data") or {})
        elif msg.type == "result" and msg.in_reply_to in pending:
            pending[msg.in_reply_to] = msg.payload
    gateway.attach_executor(router, "bot_01")
    gateway.attach_agent(agent_obj, "proc_01")
    gateway.run()

    print(f"== APA po-approval: Process Mode 订单{'超预算' if over_budget else '小额'}审批 ==")
    print(f"→ 触发事件 erp.order.approval_requested {{context: {order_ref}}}")
    router.emit("erp.order.approval_requested", {
        "context": order_ref,
        "available_actions": ["erp.order.approve", "erp.order.reject"],
        "notify_url": f"http://127.0.0.1:{ERP_PORT}/notify",
    })

    deadline = time.time() + 10
    while time.time() < deadline:
        if engine.run.done:
            break
        gateway.tick()
        time.sleep(0.02)

    summary = gateway.summary()
    print("\n流程步骤：")
    for s in engine.run.steps:
        print(f"  · {s}")
    print(f"\nERP 收到: {erp.requests}")
    print(f"Session: {summary['state']}  outcome={engine.run.outcome}")

    expected_action = "/approve" if not over_budget else "/reject"
    ok = (engine.run.done and summary["state"] == "COMPLETED"
          and any(str(r.get("path", "")).endswith(expected_action)
                  for r in erp.requests))
    print("\nRESULT:", f"OK — 订单已{'批准' if not over_budget else '驳回'}" if ok else "FAILED")
    erp.stop()
    return 0 if ok else 1



class _Passthrough:
    """agent 侧占位对象：消息路由由 set_handler 的 agent_inbox 直接接管。"""

    def __init__(self, on_message) -> None:
        self.on_message = on_message
        self.peer = AIPPeer(source="proc_01", session_id=SESSION)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="APA po-approval (Process Mode)")
    parser.add_argument("--over", action="store_true", help="使用超预算订单")
    args = parser.parse_args()
    raise SystemExit(run(over_budget=args.over))