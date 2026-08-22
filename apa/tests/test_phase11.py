"""Phase 11：cordis 实机联调 + serve 常驻模式。"""
import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from apa_core.registry import load_registries

APA_ROOT = Path(__file__).resolve().parent.parent
SESSION = "s_p11_001"
EXEC, AGENT = "bot_01", "node_agent"


def registries():
    return load_registries(APA_ROOT / "registries" / "core.yaml",
                           APA_ROOT / "registries" / "browser.yaml")


def node_available() -> bool:
    import shutil
    return shutil.which("node") is not None


# --- cordis 实机联调 -----------------------------------------------------------------
@pytest.mark.skipif(not node_available(), reason="node not installed")
class TestCordisRuntime:
    def test_real_container_mounts_plugin(self):
        """真实 cordis 容器：Service 提供 → inject 解析 → apply → 决策闭环。"""
        asyncio.run(self._scenario())

    async def _scenario(self):
        import websockets

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
        page.elements = [
            __import__("apa_sdk.testing", fromlist=["MockElement"])
            .MockElement(role="button", text="批准",
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
        gw.attach_executor(executor, EXEC)

        host = APA_ROOT / "plugins" / "dsh" / "tests" / "cordis_host.mjs"
        proc = await asyncio.create_subprocess_exec(
            "node", str(host), url, SESSION, AGENT,
            "browser.page.loaded", "browser.click", "approve-btn",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)

        connected = False
        for _ in range(100):
            if gateway.connected.get("agent"):
                connected = True
                break
            await asyncio.sleep(0.05)
        assert connected, "cordis 容器内的插件从未连接网关"

        gw.run()
        executor.trigger_navigate("https://erp.corp/po/cordis")

        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=20)
        finally:
            out = await proc.stdout.read()
        log = out.decode("utf-8", errors="replace")
        print("\n--- cordis host log ---\n" + log)

        assert rc == 0, f"host exited {rc}\n{log}"
        assert "decision #1" in log, log          # mock-llm 确被调用
        assert page.clicked == ["approve-btn"], page.clicked
        await server.close()


# --- serve 常驻模式 ------------------------------------------------------------------
class TestServeMode:
    def test_event_job_runs_process_and_hits_erp(self, tmp_path):
        """event 任务 → 后台线程跑流程 → journal COMPLETED + ERP 收到通知。"""
        from apa_core.serve import ServeApp

        procs = tmp_path / "procs"
        procs.mkdir()

        notify_port_holder: dict = {}

        # 本地 HTTP 目标（供流程 POST /notify）
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        hits: list = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                hits.append(json.loads(body or b"{}"))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        notify_port_holder["port"] = srv.server_address[1]

        (procs / "serve_demo.yaml").write_text(
            "process:\n"
            "  id: serve_demo\n"
            "  mode: process\n"
            "  trigger: {type: event, name: e.serve.tick}\n"
            "  steps:\n"
            "    - id: n1\n"
            "      action: api.http.post\n"
            f"      params: {{url: 'http://127.0.0.1:{notify_port_holder['port']}/notify', "
            "json: {src: serve}}\n",
            encoding="utf-8")

        from apa_core.serve import ServeApp

        app = ServeApp(
            journals=[str(tmp_path / "*.jsonl")],
            processes_dir=str(procs),
            registry=load_registries(
                APA_ROOT / "registries" / "core.yaml",
                APA_ROOT / "registries" / "browser.yaml",
                APA_ROOT / "registries" / "api.yaml"),
            mock_erp=False,          # 流程目标为本地 HTTP，无需内置 ERP
            runs_dir=str(tmp_path / "runs"),
            tick_interval_s=0.2,
            session_timeout_s=15.0,
        )
        app.add_process_job(
            "serve_demo_job",
            kind="event",
            process="serve_demo",
            event="e.serve.tick",
        )
        port = app.studio_start_background()
        assert port > 0

        r = app.dispatch_external_event("e.serve.tick", {"src": "pytest"})
        assert r["dispatched"] == 1

        deadline = time.time() + 12
        completed = False
        while time.time() < deadline:
            for p in tmp_path.rglob("*.jsonl"):
                text = p.read_text(encoding="utf-8")
                if '"to": "COMPLETED"' in text and "s_serve_" in text:
                    completed = True
                    break
            if completed:
                break
            time.sleep(0.1)
        assert completed, "serve 会话未在期限内完成"

        assert len(hits) == 1 and hits[0].get("src") == "serve"
        app.shutdown()


# --- scheduler.yaml 批量加载 ---------------------------------------------------------
class TestLoadJobs:
    def test_yaml_jobs_loaded(self, tmp_path):
        jpath = tmp_path / "scheduler.yaml"
        jpath.write_text(
            "jobs:\n"
            "  - id: cron_job\n"
            "    kind: cron\n"
            "    expr: '*/30 * * * *'\n"
            "    process: some_flow\n"
            "  - id: evt_job\n"
            "    kind: event\n"
            "    event: e.incoming.x\n"
            "    process: other_flow\n",
            encoding="utf-8")
        from apa_core.serve import ServeApp

        app = ServeApp([str(tmp_path / "*.jsonl")], port=0,
                       processes_dir=str(procs_dir := tmp_path / "p"),
                       mock_erp=False)
        n = app.load_jobs(str(jpath))
        assert n == 2
        assert app.scheduler.summary()["by_kind"] == {"cron": 1, "event": 1}
        app.shutdown()


class TestCronJobFires:
    def test_cron_job_fires_within_minute(self, tmp_path):
        """真实时间：每分钟 cron 在下一个整分钟边界触发（≤60s）。"""
        from apa_core.serve import ServeApp

        fired_flag = {"fired": False}

        app = ServeApp(journals=[str(tmp_path / "*.jsonl")], port=0,
                       mock_erp=False, tick_interval_s=0.2)
        app.scheduler.add_cron("every_min", "* * * * *",
                               lambda job: fired_flag.update(fired=True))
        app.studio_start_background()
        deadline = time.time() + 65
        while time.time() < deadline and not fired_flag["fired"]:
            time.sleep(0.2)
        assert fired_flag["fired"], "60 秒内 cron 未触发"
        app.shutdown()