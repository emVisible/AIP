"""Webhook 触发器端到端测试：HTTP POST /api/events → 流程运行 → journal 完成。

链路：curl/客户端 → FastAPI /api/events → ServeApp.dispatch_external_event
      → Scheduler event job → ProcessRunner 执行 process.yaml → journal
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from starlette.testclient import TestClient

from apa_core.api import create_app
from apa_core.registry import load_registries
from apa_core.serve import ServeApp

APA_ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])


@pytest.fixture()
def notify_server():
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
    yield srv.server_address[1], hits
    srv.shutdown()


def test_webhook_triggers_process_e2e(tmp_path, notify_server):
    port_notify, hits = notify_server

    procs = tmp_path / "procs"
    procs.mkdir()
    (procs / "webhook_demo.yaml").write_text(
        "process:\n"
        "  id: webhook_demo\n"
        "  mode: process\n"
        "  trigger: {type: event, name: webhook.order.created}\n"
        "  steps:\n"
        "    - id: notify\n"
        "      action: api.http.post\n"
        f"      params: {{url: 'http://127.0.0.1:{port_notify}/cb', "
        "json: {order: '{{event.data.order_id}}'}}\n",
        encoding="utf-8")

    serve_app = ServeApp(
        journals=[str(tmp_path / "*.jsonl")],
        processes_dir=str(procs),
        registry=load_registries(
            APA_ROOT + "/registries/core.yaml",
            APA_ROOT + "/registries/api.yaml"),
        mock_erp=False,
        runs_dir=str(tmp_path / "runs"),
        tick_interval_s=0.2,
        session_timeout_s=15.0,
    )
    serve_app.add_process_job(
        "wh_job", kind="event",
        process="webhook_demo", event="webhook.order.created")
    serve_app.studio_start_background()

    fast_app = create_app(
        journals=[str(tmp_path / "*.jsonl")],
        processes_dir=str(procs),
        registry=load_registries(
            APA_ROOT + "/registries/core.yaml",
            APA_ROOT + "/registries/api.yaml"),
        ai_status={"mode": "rules_only"},
        dispatch_event=serve_app.dispatch_external_event,
    )
    client = TestClient(fast_app)

    # ---- 模拟外部系统 webhook 调用 -------------------------------------
    r = client.post("/api/events", json={
        "name": "webhook.order.created",
        "data": {"order_id": "WH-777"},
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"dispatched": 1}

    # 未配置事件名 → 不命中
    r2 = client.post("/api/events", json={
        "name": "nobody.listens", "data": {}})
    assert r2.json()["dispatched"] == 0

    # ---- 等待后台流程完成并回调 ----------------------------------------
    deadline = time.time() + 12
    while time.time() < deadline and not hits:
        time.sleep(0.1)
    assert hits, "webhook 流程未在期限内执行"
    assert hits[0]["order"] == "WH-777", hits

    serve_app.shutdown()
