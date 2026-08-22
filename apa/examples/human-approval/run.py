#!/usr/bin/env python3
"""APA human-approval — 浏览器人工审批交互演示（HITL，§4.3）。

大额发票 → 提取字段 → 超阈值 → Session SUSPENDED →
打开浏览器在 APA-Studio 点「批准/驳回」→ 会话恢复继续流转。

    python run.py                # 默认端口 8690，Ctrl-C 退出
    python run.py --auto approve # 无头自检：自动批准（CI 用）
"""
import argparse
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
from apa_core.persist import SessionJournal
from apa_core.policy import PolicyConfig
from apa_core.registry import load_registries
from apa_core.rules import RuleBasedAgent, RuleEngine
from apa_core.studio import StudioServer

from apa_executors.api_executor import APIExecutor
from apa_executors.document_executor import DocumentExecutor
from apa_sdk.composite import CompositeExecutor

SESSION = "s_hitl_001"


def run(auto: str = "") -> int:
    registries = load_registries(
        APA_ROOT / "registries" / "core.yaml",
        APA_ROOT / "registries" / "document.yaml",
        APA_ROOT / "registries" / "api.yaml")

    journal_path = HERE / ".session.jsonl"
    if journal_path.exists():
        journal_path.unlink()  # 每次演示从零开始

    erp = MockERP()
    ERP_PORT = erp.start()

    gateway = EmbeddedGateway(
        SESSION,
        registry=registries,
        policy=PolicyConfig(),
        identities={"executor": "bot_01", "agent": "rule_01"},
        process_id="human_approval",
        tenant_id="demo",
        journal=SessionJournal(journal_path),
    )

    router = CompositeExecutor("bot_01", SESSION)
    doc_mod = DocumentExecutor("bot_01", SESSION)
    api_mod = APIExecutor("bot_01", SESSION,
                          base_url=f"http://127.0.0.1:{ERP_PORT}")
    router.register(("doc",), doc_mod)
    router.register(("api", "erp"), api_mod)

    agent = RuleBasedAgent(
        AIPPeer(source="rule_01", session_id=SESSION),
        RuleEngine.from_yaml(str(HERE / "rules.yaml")),
    )

    gw = gateway.gateway
    gateway.attach_executor(router, "bot_01")
    gateway.attach_agent(agent, "rule_01")
    gateway.run()
    router.start_observation()

    # Studio：网页按钮 → resolve 回调 → 网关注入完成事件 → 恢复
    studio = StudioServer(
        [str(journal_path)], port=8690,
        resolve_task=lambda tid, outcome, actor="studio":
            gw.resolve_human_task(tid, outcome=outcome, actor=actor),
    )
    studio_port = studio.start_background()
    url = f"http://127.0.0.1:{studio_port}"
    print("== APA Human-in-the-Loop 交互演示 ==")
    print(f"→ 大额发票进入流程，等待人工审批")
    print(f"→ 打开浏览器：{url}   （点「批准」或「驳回」）")

    router.emit("document.processing.started", {
        "path": str(HERE / "sample_invoice_large.txt"),
        "context": "ctx_s_hitl_001_doc",
    })

    if auto:
        # 无头自检：模拟按钮 POST（与浏览器行为完全一致）
        import json as _json
        import urllib.request

        def click(outcome: str) -> None:
            task_id = gw.human.open_tasks()[0]["task_id"]
            req = urllib.request.Request(
                f"http://127.0.0.1:{studio_port}/api/tasks/{task_id}/resolve",
                data=_json.dumps({"outcome": outcome}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert _json.loads(resp.read())["ok"] is True

        deadline = time.time() + 10
        while time.time() < deadline and not gw.human.open_tasks():
            time.sleep(0.05)
        time.sleep(0.2)
        click(auto)
        print(f"→ [auto] 已点击「{auto}」")

    deadline = time.time() + (120 if not auto else 30)
    while time.time() < deadline:
        if agent.done and gw.summary()["state"] == "COMPLETED":
            break
        gw.tick()
        time.sleep(0.05)

    summary = gw.summary()
    print("\n决策引擎步骤：")
    for step in agent.steps:
        print(f"  · {step}")
    print(f"\nERP 发票: {erp.invoices}")
    print(f"Session: {summary['state']}  outcome={gw.sm.record.outcome}")

    ok = summary["state"] == "COMPLETED"
    if auto == "approve":
        ok = ok and len(erp.invoices) == 1 \
            and erp.invoices[0].get("invoice_no") == "INV-2026-0099"
    elif auto == "reject":
        ok = ok and not erp.invoices
    print("\nRESULT:", "OK — 人工闭环完成" if ok else "FAILED")
    erp.stop()
    studio.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="APA HITL 交互演示")
    parser.add_argument("--auto", choices=["approve", "reject"], default="",
                        help="无头自检：模拟按钮点击后退出")
    args = parser.parse_args()
    raise SystemExit(run(auto=args.auto))