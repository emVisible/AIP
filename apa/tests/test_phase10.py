"""Phase 10：dsh 胶水运行时验证 + 低代码设计器后端。"""
import asyncio
import json
from pathlib import Path

import pytest

from aip import make_action, make_event

from apa_core.registry import load_registries

APA_ROOT = Path(__file__).resolve().parent.parent
SESSION = "s_p10_001"
EXEC, AGENT = "bot_01", "node_agent"


def registries():
    return load_registries(APA_ROOT / "registries" / "core.yaml",
                           APA_ROOT / "registries" / "browser.yaml")


def node_available() -> bool:
    import shutil
    return shutil.which("node") is not None


@pytest.fixture(scope="module", autouse=True)
def ensure_protocol_link():
    base = APA_ROOT / "plugins" / "dsh" / "node_modules" / "@aip"
    link = base / "protocol"
    if not link.exists():
        base.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(Path("../../../../../sdk/typescript"))
        except OSError:
            pass
    yield


# --- dsh 胶水 apply() 运行时 -------------------------------------------------------
@pytest.mark.skipif(not node_available(), reason="node not installed")
class TestDshGlueRuntime:
    def test_apply_drives_decision_loop(self):
        asyncio.run(self._scenario())

    async def _scenario(self):
        import websockets

        from aip import AIPPeer as _P  # noqa: F401

        from apa_core.embedded import EmbeddedGateway
        from apa_core.policy import PolicyConfig
        from apa_core.ws_gateway import WsGatewayServer
        from apa_executors.browser_executor import BrowserExecutor
        from apa_sdk.semantic_adapter import SemanticAdapter
        from apa_sdk.testing import MockElement, MockPage

        gw = EmbeddedGateway(SESSION, registry=registries(),
                             policy=PolicyConfig(),
                             identities={"executor": EXEC, "agent": AGENT})
        gateway = gw.gateway

        page = MockPage()
        page.title = "待审批采购订单"
        page.elements = [MockElement(role="button", text="批准",
                                     data_apa_id="approve-btn")]
        adapter = SemanticAdapter({"semantic_patterns": [{
            "trigger": {"url_pattern": "*"},
            "emit": {"event": "browser.page.loaded",
                     "data_mapping": {"url": {"selector": "__url__"}}},
        }]})
        executor = BrowserExecutor(EXEC, SESSION, page=page, adapter=adapter)

        server = WsGatewayServer(gateway, port=0)
        port = await server.start()
        url = f"ws://127.0.0.1:{port}"

        client = APA_ROOT / "plugins" / "dsh" / "tests" / "glue_smoke.mjs"
        proc = await asyncio.create_subprocess_exec(
            "node", str(client), url, SESSION, AGENT,
            "browser.page.loaded", "browser.click", "approve-btn",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)

        connected = False
        for _ in range(100):
            if gateway.connected.get("agent"):
                connected = True
                break
            await asyncio.sleep(0.05)
        assert connected, "apply() never said hello"

        gw.attach_executor(executor, EXEC)   # 执行器接入网关（事件/动作通路）
        gw.run()
        executor.trigger_navigate("https://erp.corp/po/9")

        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=15)
        finally:
            out = await proc.stdout.read()
        log = out.decode("utf-8", errors="replace")
        print("\n--- glue smoke log ---\n" + log)

        assert rc == 0, f"glue exited {rc}\n{log}"
        assert page.clicked == ["approve-btn"], page.clicked
        await server.close()


# --- 低代码：Registry 动作目录 API（编辑器表单数据源） -------------------------------
class TestLowcodeBackend:
    def test_registry_actions_listing(self, tmp_path):
        """编辑器表单的数据源：动作名 → 参数 schema/风险/域。"""
        from apa_core.studio import StudioServer
        studio = StudioServer([str(tmp_path / "none.jsonl")], port=0,
                              registry=registries())
        actions = studio.registry_actions()
        assert "browser.click" in actions
        click = actions["browser.click"]
        assert click["risk"] == "L1"
        assert set(click["params"]["properties"]) >= {"target"}
        assert actions["context.get"]["executor_domain"] == "any"