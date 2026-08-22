#!/usr/bin/env python3
"""APA invoice-processing — v0.2 验收场景（设计文档 §16.2）。

流程：文档到达 → 提取发票字段 → 规则校验 → 写入 ERP（本地 mock HTTP）→ 完成。

    python run.py            # 纯规则（L0），确定性
    python run.py --llm      # 级联演示：规则未命中时走 LLM 决策
                             # （需 APA_LLM_API_KEY；未配置自动退回脚本化 FakeLLM）
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

from apa_core.cascade import CascadingAgent
from apa_core.embedded import EmbeddedGateway
from apa_core.llm import FakeLLMClient, LLMClient
from apa_core.mock_erp import MockERP
from apa_core.policy import PolicyConfig
from apa_core.registry import load_registries

from apa_executors.api_executor import APIExecutor
from apa_executors.document_executor import DocumentExecutor
from apa_sdk.composite import CompositeExecutor

SESSION = "s_inv_001"


def build_agent(peer, rules, use_llm: bool):
    if not use_llm:
        from apa_core.rules import RuleBasedAgent
        return RuleBasedAgent(peer, rules)
    try:
        llm = LLMClient()  # 需 APA_LLM_API_KEY
    except Exception:
        # 无 Key：脚本化 FakeLLM 演示 L1 分支（规则未命中时分类文档）
        llm = FakeLLMClient(responses=[
            {"action": "doc.classify",
             "params": {"document_ref": str(HERE / "sample_invoice.txt")}},
        ])
    return CascadingAgent(
        peer, rules, llm,
        allowed_actions=["doc.extract_fields", "doc.extract_text",
                         "doc.classify", "erp.invoice.create",
                         "human.task.create"],
    )


def run(use_llm: bool) -> int:
    registries = load_registries(
        APA_ROOT / "registries" / "core.yaml",
        APA_ROOT / "registries" / "document.yaml",
        APA_ROOT / "registries" / "api.yaml")
    gateway = EmbeddedGateway(
        SESSION,
        registry=registries,
        policy=PolicyConfig(),
        identities={"executor": "bot_01", "agent": "rule_01"},
        process_id="invoice_processing",
    )

    erp = MockERP()
    ERP_PORT = erp.start()

    # 单协议身份 bot_01，多领域能力：doc.* / api.* / erp.*
    router = CompositeExecutor("bot_01", SESSION)
    doc_mod = DocumentExecutor("bot_01", SESSION)
    api_mod = APIExecutor("bot_01", SESSION,
                          base_url=f"http://127.0.0.1:{ERP_PORT}")
    router.register(("doc",), doc_mod)
    router.register(("api", "erp"), api_mod)

    from apa_core.rules import RuleEngine
    rules = RuleEngine.from_yaml(str(HERE / "rules.yaml"))
    agent = build_agent(AIPPeer(source="rule_01", session_id=SESSION),
                        rules, use_llm)

    gateway.attach_executor(router, "bot_01")
    gateway.attach_agent(agent, "rule_01")
    gateway.run()
    router.start_observation()

    print("== APA invoice-processing: 发票扫描 → 提取 → 写 ERP ==")
    print(f"→ 文档: {HERE / 'sample_invoice.txt'}")
    router.emit("document.processing.started", {
        "path": str(HERE / "sample_invoice.txt"),
        "context": "ctx_s_inv_001_doc",
    })

    deadline = time.time() + 10
    while time.time() < deadline and not agent.done:
        gateway.tick()
        time.sleep(0.02)

    summary = gateway.summary()
    print("\n决策引擎步骤：")
    for step in agent.steps:
        print(f"  · {step}")
    fields = router.context_store.snapshot("ctx_s_inv_001_fields") or {}
    print(f"\n提取字段: {fields}")
    print(f"ERP 收到的发票: {erp.invoices}")
    extra = f"  决策分布: {agent.stats}" if hasattr(agent, "stats") else ""
    print(f"Session: {summary['state']}{extra}")

    ok = (summary["state"] == "COMPLETED" and len(erp.invoices) == 1
          and erp.invoices[0].get("invoice_no") == "INV-2026-0042"
          and fields.get("total_num") == 30000.0)
    print("\nRESULT:", "OK — 发票已入 ERP" if ok else "FAILED")
    erp.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="APA invoice-processing")
    parser.add_argument("--llm", action="store_true",
                        help="启用级联决策（规则未命中走 LLM）")
    args = parser.parse_args()
    raise SystemExit(run(use_llm=args.llm))