"""Phase 6：跨语言 E2E —— Node(@aip/protocol) 决策端 ↔ Python WsGatewayServer。

验证 apa/plugins/dsh 的协议核心与 Python 网关的线级兼容性：
hello 握手（D1）、ping/pong（D4）、事件→动作→结果闭环、per-stream seq。
Node 侧使用与 dsh 插件完全相同的 AIPPeer + WsClientTransport 代码路径。
"""
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from apa_core.policy import PolicyConfig
from apa_core.registry import load_registries

APA_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APA_ROOT.parent
SESSION = "s_xlang_001"
EXEC, AGENT = "bot_01", "node_agent"
CLIENT = APA_ROOT / "plugins" / "dsh" / "tests" / "e2e_client.mjs"


def registries():
    return load_registries(
        APA_ROOT / "registries" / "core.yaml",
        APA_ROOT / "registries" / "browser.yaml")


def node_available() -> bool:
    return shutil.which("node") is not None


@pytest.fixture(scope="module", autouse=True)
def ensure_protocol_link():
    """确保 @aip/protocol 可解析（CI 与本地同一路径）。"""
    base = APA_ROOT / "plugins" / "dsh" / "node_modules" / "@aip"
    link = base / "protocol"
    if not link.exists():
        base.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(Path("../../../../../sdk/typescript"))
        except OSError:
            pass  # 无法建链时让用例以明确的模块错误失败
    yield


class TestCrossLanguage:
    @pytest.mark.skipif(not node_available(), reason="node not installed")
    def test_node_agent_full_loop(self):
        """Node 决策端完整闭环：hello → event → action → result ok。"""
        asyncio.run(self._scenario())

    async def _scenario(self):
        import websockets  # noqa: F401  (确保依赖存在)

        from aip import AIPPeer

        from apa_core.embedded import EmbeddedGateway
        from apa_core.policy import PolicyConfig
        from apa_core.ws_gateway import WsGatewayServer
        from apa_executors.browser_executor import BrowserExecutor
        from apa_sdk.semantic_adapter import SemanticAdapter
        from apa_sdk.testing import MockElement, MockPage

        gw = EmbeddedGateway(
            SESSION,
            registry=registries(),
            policy=PolicyConfig(),
            identities={"executor": EXEC, "agent": AGENT},
        )
        gateway = gw.gateway

        page = MockPage()
        page.title = "待审批采购订单"
        page.elements = [
            __import__("apa_sdk.testing", fromlist=["MockElement"])
            and MockElement(role="button", text="批准", data_apa_id="approve-btn"),
        ]
        adapter = SemanticAdapter({"semantic_patterns": [{
            "trigger": {"url_pattern": "*"},
            "emit": {"event": "browser.page.loaded",
                     "data_mapping": {"url": {"selector": "__url__"},
                                      "title": {"selector": "__title__"}}},
        }]})
        executor = BrowserExecutor(EXEC, SESSION, page=page, adapter=adapter)

        server = WsGatewayServer(gateway, port=0)
        port = await server.start()
        url = f"ws://127.0.0.1:{port}"

        gw.attach_executor(executor, EXEC)

        # Node 子进程作为决策端
        proc = await asyncio.create_subprocess_exec(
            "node", str(CLIENT), url, SESSION, AGENT,
            "browser.page.loaded", "browser.click", "approve-btn",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # 等 agent 接入（hello 完成 → connected["agent"]=True）
        connected = False
        for _ in range(100):
            if gateway.connected.get("agent"):
                connected = True
                break
            await asyncio.sleep(0.05)
        assert connected, "node client never said hello"

        # 触发页面事件 → 应驱动 node 端决策 → 点击回流执行
        gw.run()
        executor.trigger_navigate("https://erp.corp/po/1")

        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=15)
        finally:
            out = await proc.stdout.read()
        node_log = out.decode("utf-8", errors="replace")
        print("\n--- node client log ---\n" + node_log)

        assert rc == 0, f"node client exited {rc}\n{node_log}"
        assert "terminal ok" in node_log
        assert page.clicked == ["approve-btn"], page.clicked
        assert gateway.sm.state in ("RUNNING",)
        await server.close()