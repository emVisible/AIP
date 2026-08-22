#!/usr/bin/env python3
"""APA hello-rpa — 最小可运行示例（设计文档 §14.2）。

流程（E→D→A→R，纯规则引擎，0 LLM Token）：
    导航到采购订单待办页
      → 语义适配器识别审批对话框 → erp.order.approval_requested
      → 规则：金额 < 100000 → browser.click 批准
      → 提取结果消息 → session.complete

运行：
    python run.py            # 真实 Playwright（headless）
    python run.py --mock     # 无浏览器（CI/测试用）

输出：
    RESULT: OK — 已审批订单 PO-5678  事件数 N 动作数 M  Token 消耗 0
"""
import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APA_ROOT = HERE.parent.parent

sys.path.insert(0, str(APA_ROOT / "packages" / "apa-core"))
sys.path.insert(0, str(APA_ROOT / "packages" / "apa-sdk-python"))
sys.path.insert(0, str(APA_ROOT / "packages" / "apa-executors"))
sys.path.insert(0, str(APA_ROOT / "sdk" / "python"))

from aip import AIPPeer

from apa_core.embedded import EmbeddedGateway
from apa_core.policy import PolicyConfig
from apa_core.registry import load_registries
from apa_core.rules import RuleBasedAgent

from apa_executors.browser_executor import BrowserExecutor
from apa_sdk.semantic_adapter import SemanticAdapter
from apa_sdk.testing import MockElement, MockPage

LOG: list = []


def build_page_mock() -> MockPage:
    """模拟 test_page/index.html 的可访问性模型（供 --mock 与测试）。"""
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
    return page


def make_mock_click(page: MockPage) -> None:
    """让 MockPage 的批准按钮点击更新结果区（模拟真实页面的 JS）。"""

    orig_click = page.click

    def click(target: str, force: bool = False) -> None:
        orig_click(target, force=force)
        if target == "approve-btn-1":
            for el in page.elements:
                if el.data_apa_id == "result":
                    el.text = "已批准订单 PO-5678"
    page.click = click


def run(mock: bool = False) -> int:
    registries = load_registries(
        str(APA_ROOT / "registries" / "core.yaml"),
        str(APA_ROOT / "registries" / "browser.yaml"),
        str(APA_ROOT / "registries" / "api.yaml"),
    )
    gateway = EmbeddedGateway(
        "s_hello_001",
        registry=registries,
        policy=PolicyConfig(),
        identities={"executor": "browser_01", "agent": "rule_01"},
        process_id="hello_rpa",
        tenant_id="demo",
    )

    if mock:
        page = build_page_mock()
        make_mock_click(page)
        adapter = SemanticAdapter.from_yaml(str(HERE / "schema.yaml"))
        executor = BrowserExecutor("browser_01", "s_hello_001", page=page, adapter=adapter)
    else:
        from apa_executors.browser_executor import open_browser
        pw, browser, page, page_ops = open_browser(headless=True)
        adapter = SemanticAdapter.from_yaml(str(HERE / "schema.yaml"))
        executor = BrowserExecutor("browser_01", "s_hello_001", page=page_ops, adapter=adapter)

    from apa_core.rules import RuleEngine
    agent = RuleBasedAgent(
        AIPPeer(source="rule_01", session_id="s_hello_001"),
        RuleEngine.from_yaml(str(HERE / "rules.yaml")),
    )

    gateway.attach_executor(executor, "browser_01")
    gateway.attach_agent(agent, "rule_01")
    gateway.run()

    print("== APA hello-rpa: Agentic Process Automation 最小示例 ==")
    page_url = (Path(__file__).parent / "test_page" / "index.html").as_uri()
    print(f"→ 导航: {page_url}")
    executor.trigger_navigate(page_url)

    # 等待决策引擎完成（最多 15 秒）
    deadline = time.time() + 15
    while time.time() < deadline:
        if agent.done:
            break
        gateway.tick()  # 推进超时/重试
        time.sleep(0.05)

    summary = gateway.summary()
    print("\n决策引擎步骤：")
    for step in agent.steps:
        print(f"  · {step}")
    result = executor.context_store.snapshot("ctx_s_hello_001_result")
    print(f"\n提取结果: {result}")
    print(f"事件数: {summary['stats']['events']}  动作数: {summary['executions']}  "
          f"Token 消耗: 0（纯规则模式）")
    print(f"Session 状态: {summary['state']}  审计记录: {summary['audit_records']}")

    ok = (agent.done and summary["state"] == "COMPLETED"
          and result and "已批准" in str(result.get("result", "")))
    print("\nRESULT:", "OK — 已审批订单 PO-5678" if ok else "FAILED")
    if not mock:
        browser.close()
        pw.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="APA hello-rpa")
    parser.add_argument("--mock", action="store_true",
                        help="使用 MockPage（无浏览器，CI/测试用）")
    args = parser.parse_args()
    raise SystemExit(run(mock=args.mock))