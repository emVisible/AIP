"""R3 dsh 完整接入测试：run-agent.mjs 宿主 + 内嵌 WS 网关池。

链路：executor 语义事件 → WsGatewayServer → ApaDecisionAgent(run-agent)
→ L1 决策 → 网关校验 → 执行器命中。

实证要点（调试结论，防回归）：
  - 场景必须运行在单一事件循环内；轮询用 asyncio.sleep 让渡循环，
    否则 hello/泵协程得不到调度（time.sleep 会饿死它们）
  - gateway.connected 默认全 True（嵌入式回路的假信号），
    真实接入判定只能看 server.conns
  - 跨线程 enqueue 必须走 call_soon_threadsafe（见 _make_enqueuer）
"""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from apa_core.registry import load_registries

APA_DIR = Path(__file__).resolve().parents[1]
RUN_AGENT = APA_DIR / "plugins" / "dsh" / "run-agent.mjs"
CORDIS_HOST = APA_DIR / "plugins" / "dsh" / "tests" / "cordis_host.mjs"

SESSION = "s_dsh_e2e"
T0 = time.time()


def ts() -> float:
    return round(time.time() - T0, 2)


def node_available() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True,
                       check=True, timeout=10)
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(sys.platform != "darwin", reason="本机验证优先"),
    pytest.mark.skipif(not node_available(), reason="node 不可用"),
]


def build_gateway():
    from apa_core.embedded import EmbeddedGateway
    from apa_core.policy import PolicyConfig
    from apa_sdk.testing import MockElement, MockPage

    gw = EmbeddedGateway(
        SESSION,
        registry=load_registries(
            str(APA_DIR / "registries" / "core.yaml"),
            str(APA_DIR / "registries" / "browser.yaml")),
        policy=PolicyConfig(),
        identities={"executor": "browser_01",
                    "agent": ["rule_01", "dsh_agent_001"]},
        process_id="dsh_e2e",
    )
    page = MockPage()
    page.title = "PO 审批"
    page.elements = [
        MockElement(role="button", text="批准",
                    data_apa_id="approve-btn")]
    return gw, page


async def wait_agent(server, timeout_s=10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if len(server.conns.get(SESSION, {}).get("agent", [])) > 0:
            return True
        await asyncio.sleep(0.05)
    return False


async def wait_click(page, timeout_s=10.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline and not page.clicked:
        await asyncio.sleep(0.05)


def spawn_host(variant: str, port: int) -> subprocess.Popen:
    if variant == "run-agent":
        cmd = ["node", str(RUN_AGENT),
               "--gateway", f"ws://127.0.0.1:{port}",
               "--session", SESSION,
               "--source", "dsh_agent_001",
               "--tenant", "test",
               "--actions", "human.task.create,browser.click",
               "--mock", "--mock-action", "browser.click",
               "--mock-target", "approve-btn",
               "--lifetime-ms", "20000"]
    else:  # cordis 对照组
        cmd = ["node", str(CORDIS_HOST),
               f"ws://127.0.0.1:{port}", SESSION, "dsh_agent_001",
               "browser.page.loaded", "browser.click", "approve-btn"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)


VARIANTS = ["run-agent"]
if CORDIS_HOST.exists():
    VARIANTS.append("cordis")


@pytest.mark.parametrize("variant", VARIANTS)
def test_host_decision_e2e(variant):
    """宿主接入 → 事件决策 → 动作命中执行器。"""
    import asyncio

    from apa_core.ws_gateway import WsGatewayServer
    from apa_executors.browser_executor import BrowserExecutor
    from apa_sdk.semantic_adapter import SemanticAdapter

    async def scenario():
        gw, page = build_gateway()
        executor = BrowserExecutor(
            "browser_01", SESSION, page=page,
            adapter=SemanticAdapter({"semantic_patterns": [{
                "trigger": {"url_pattern": "*"},
                "emit": {"event": "browser.page.loaded",
                         "data_mapping": {"url": {"selector": "__url__"}}},
            }]}))

        server = WsGatewayServer(gw.gateway, port=0)
        port = await server.start()
        gw.attach_executor(executor, "browser_01")

        proc = spawn_host(variant, port)
        try:
            connected = await wait_agent(server)
            assert connected, \
                f"[{variant}] host 未接入；conns={dict(server.conns)}"

            gw.run()
            executor.trigger_navigate("https://erp.corp/po/dsh")
            await wait_click(page)

            diag = {"clicked": page.clicked,
                    "conns": {k: len(v) for k, v in server.conns.items()}}
            assert page.clicked == ["approve-btn"], f"{variant} {diag}"

            rc = proc.wait(timeout=25)
            out = proc.stdout.read()
            assert rc == 0, f"[{variant}] host exited {rc}\n{out}"
        finally:
            if proc.poll() is None:
                proc.kill()
            await server.close()

    asyncio.run(scenario())


def test_ws_gateway_dynamic_register():
    """register_session/unregister_session 动态池管理。"""
    import asyncio

    from apa_core.policy import PolicyConfig
    from apa_core.ws_gateway import WsGatewayServer

    async def main():
        from apa_core.embedded import EmbeddedGateway

        def mk(sid):
            return EmbeddedGateway(
                sid, registry=load_registries(
                    str(APA_DIR / "registries" / "core.yaml")),
                policy=PolicyConfig(),
                identities={"executor": "e", "agent": "a"})

        gw1 = mk("s_a")
        server = WsGatewayServer(gw1.gateway, port=0)
        await server.start()

        gw2 = mk("s_b")
        assert server.register_session("s_b", gw2.gateway) is True
        assert server.register_session("s_b", gw2.gateway) is False
        assert "s_b" in server.gateways

        server.unregister_session("s_b")
        assert "s_b" not in server.gateways
        await server.close()

    asyncio.run(main())