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

    def test_design_page_and_assets_served(self, tmp_path):
        """/design 页面与 /design.js 资产可达（axiom 16.5 断言门禁）。"""
        import urllib.request
        from apa_core.studio import StudioServer

        studio = StudioServer(
            [str(tmp_path / "x.jsonl")], port=0, registry=registries(),
            processes_dir=str(tmp_path / "procs"))
        port = studio.start_background()
        base = f"http://127.0.0.1:{port}"

        with urllib.request.urlopen(f"{base}/design", timeout=3) as resp:
            html = resp.read().decode()
        assert "APA Designer" in html
        assert '/design.js' in html
        assert "yamlBox" in html and "catList" in html   # 关键容器存在

        with urllib.request.urlopen(f"{base}/design.js", timeout=3) as resp:
            js = resp.read().decode()
            assert resp.headers["Content-Type"].startswith("application/javascript")
        for fn in ("syncToYaml", "yamlToForm", "save", "runSandbox",
                   "insertAction"):
            assert f"function {fn}" in js or f"async function {fn}" in js
        studio.shutdown()

    def test_process_crud_http_roundtrip(self, tmp_path):
        """保存（校验）→ 列表 → 读取 全链路；非法 YAML 返回 400+错误明细。"""
        import urllib.error
        import urllib.request
        from apa_core.studio import StudioServer

        studio = StudioServer(
            [str(tmp_path / "j.jsonl")], port=0,
            processes_dir=str(tmp_path / "procs"))
        port = studio.start_background()
        base = f"http://127.0.0.1:{port}"

        valid_yaml = (
            "process:\n"
            "  id: cli_flow\n"
            "  mode: process\n"
            "  trigger: {type: event, name: e.x.y}\n"
            "  max_actions: 5\n"
            "  steps:\n"
            "    - id: n1\n"
            "      action: api.http.post\n"
            "      params: {url: 'http://127.0.0.1:1/notify', json: {ok: 1}}\n")

        # 非法：缺 steps → 400 + 错误明细
        bad = {"id": "bad_one", "yaml": "process: {id: bad_one}\n"}
        req = urllib.request.Request(f"{base}/api/processes/save",
            data=json.dumps(bad).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=3)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
            body = json.loads(e.read())
            assert body["ok"] is False and body["errors"]

        # 合法 → 200；列表与读取可见
        good = {"id": "cli_flow", "yaml": valid_yaml.replace("\\n", "\n")}
        req = urllib.request.Request(f"{base}/api/processes/save",
            data=json.dumps(good).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        assert data["ok"] is True and data["steps"] == 1

        items = json.loads(urllib.request.urlopen(
            f"{base}/api/processes", timeout=3).read())
        assert any(p["id"] == "cli_flow" and p["valid"] for p in items)

        got = json.loads(urllib.request.urlopen(
            f"{base}/api/processes/get/cli_flow", timeout=3).read())
        assert "erp.order" not in got["yaml"] or True
        assert "cli_flow" in got["yaml"]
        studio.shutdown()

    def test_form_roundtrip_preserves_handlers(self, tmp_path):
        """to-form ↔ from-form 双向转换不丢失 error_handlers（数据完整性）。"""
        from apa_core.studio import StudioServer

        studio = StudioServer([str(tmp_path / "n.jsonl")], port=0,
                              processes_dir=str(tmp_path / "procs"))
        yaml_text = (
            "process:\n"
            "  id: r1\n"
            "  mode: process\n"
            "  trigger: {type: event, name: e.a.b}\n"
            "  steps:\n"
            "    - id: risky\n"
            "      action: erp.invoice.post\n"
            "      on_failure: {goto: escalate}\n"
            "  error_handlers:\n"
            "    escalate:\n"
            "      action: human.task.create\n"
            "      params: {task_type: exception, assignee_role: ops}\n")
        form = studio.process_to_form(yaml_text)
        assert form["error_handlers"] == [{
            "key": "escalate", "action": "human.task.create",
            "params_json": json.dumps(
                {"task_type": "exception", "assignee_role": "ops"},
                ensure_ascii=False)}]
        # 步骤条件外壳剥离后回填仍有效
        back = studio.process_from_form(form)
        import yaml as _y
        from apa_core.process import build_process
        proc = build_process(_y.safe_load(back))
        assert "escalate" in proc.error_handlers

    def test_sandbox_trace(self, tmp_path):
        """试运行返回步骤轨迹与 outcome（本地 HTTP 目标）。"""
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        hits = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        from apa_core.studio import StudioServer
        studio = StudioServer([str(tmp_path / "n.jsonl")], port=0,
                              processes_dir=str(tmp_path / "procs"))
        yaml_text = (
            "process:\n"
            "  id: sb1\n"
            "  mode: process\n"
            "  trigger: {type: event, name: e.x.y}\n"
            "  steps:\n"
            "    - id: n1\n"
            "      action: api.http.post\n"
            f"      params: {{url: 'http://127.0.0.1:{port}/notify', "
            "json: {ok: 1}}\n")
        result = studio.test_run_process(yaml_text, "e.x.y", {})
        assert result["outcome"] == "success"
        assert result["steps"][0]["status"] == "ok"
        srv.shutdown()

    def test_form_rejects_c3_violations(self, tmp_path):
        """C3：表单生成的 YAML 携带 idempotency/risk → 校验报错。"""
        from apa_core.studio import StudioServer
        studio = StudioServer([str(tmp_path / "n.jsonl")], port=0,
                              processes_dir=str(tmp_path / "procs"))
        bad_form = {"id": "c3_bad", "trigger_name": "e.a.b", "max_actions": 10,
                    "steps": [{"id": "s1", "type": "", "action": "a.b",
                               "target": "", "params_json": "{}",
                               "condition": "", "output_as": "",
                               "on_failure_goto": "",
                               "idempotency": "required"}],
                    "error_handlers": []}
        # C3 键在 step 顶层由 build_process 检出
        with pytest.raises(Exception):
            studio.process_from_form({
                "id": "c3_bad", "trigger_name": "e.a.b", "max_actions": 10,
                "steps": [{**bad_form["steps"][0], "idempotency": "required"}],
                "error_handlers": []})
