"""Phase 5 测试：VLM 视觉插槽 / Schema 录制模式 / HashiCorp Vault 对接。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from aip import make_action

from apa_core.registry import load_registries
from apa_core.vault import HashiCorpVaultBackend, VaultError

APA_ROOT = Path(__file__).resolve().parent.parent
SESSION = "s_p5_001"


def registries():
    return load_registries(
        APA_ROOT / "registries" / "core.yaml",
        APA_ROOT / "registries" / "browser.yaml")


# --- VLM 视觉插槽（C6） -----------------------------------------------------------
class TestVisionFallback:
    def _make(self, vision):
        from apa_executors.browser_executor import BrowserExecutor
        from apa_sdk.testing import MockPage
        page = MockPage()
        page.title = "Vision Demo"
        # 页面无 data-apa-id 元素 → DOM 感知为空 → 视觉降级
        ex = BrowserExecutor("bot", SESSION, page=page, vision=vision)
        return ex, page

    def test_vision_fallback_feeds_semantic_lift(self):
        from apa_sdk.semantic_adapter import Element
        from apa_sdk.semantic_adapter import SemanticAdapter
        from apa_sdk.vision import FakeVisionAdapter

        adapter = SemanticAdapter({"semantic_patterns": [{
            "trigger": {"url_pattern": "*"},
            "emit": {"event": "browser.page.loaded",
                     "data_mapping": {
                         "url": {"selector": "__url__"},
                         "btn": {"selector": "button:提交"}}}}]})
        vision = FakeVisionAdapter(responses=[[
            __import__("apa_sdk.semantic_adapter", fromlist=["Element"]).Element(
                role="button", text="提交"),
        ]])
        ex, page = self._make(vision)
        ex.adapter = adapter

        emitted = []
        orig = ex.emit
        ex.emit = lambda n, d=None: (emitted.append((n, d)), orig(n, d))
        ex.trigger_navigate("https://x.corp/form")

        assert ex.vision_fallbacks == 1
        names = [n for n, _ in emitted]
        assert "browser.page.loaded" in names
        ev_data = dict(emitted)["browser.page.loaded"]
        assert ev_data["btn"] == "提交"          # 视觉元素参与语义提升
        assert len(vision.calls) == 1            # 截图在 Executor 本地消费（C6）

    def test_c6_bounds_never_enter_protocol(self):
        """视觉产物 bounds 坐标在入协议前剥离（C6）。"""
        from apa_sdk import Element, FakeVisionAdapter
        from apa_executors.browser_executor import BrowserExecutor
        from apa_sdk.testing import MockPage

        captured = []

        class CaptureVision(FakeVisionAdapter):
            def understand_screen(self, shot):
                els = super().understand_screen(shot)
                captured.extend(els)
                return els

        vision = CaptureVision(responses=[[
            Element(role="button", text="批准",
                    bounds={"x": 10, "y": 20, "w": 80, "h": 24}),
        ]])
        page = MockPage()
        page.title = "审批"
        ex = BrowserExecutor("bot", SESSION, page=page, vision=vision)
        seen_ctx = []
        orig_put = ex.put_context
        ex.put_context = lambda name, data, **kw: (
            seen_ctx.append(data), orig_put(name, data, **kw))[1]
        ex.trigger_navigate("https://x.corp/approve")
        # 坐标剥离于入协议前：ContextStore 数据与事件均不含 bounds
        for ctx in seen_ctx:
            assert "bounds" not in json.dumps(ctx)
        assert captured and captured[0].bounds is None

    def test_vision_error_degrades_gracefully(self):
        class BoomAdapter:
            has_vlm = True
            def understand_screen(self, shot):
                raise RuntimeError("quota exceeded")

        from apa_executors.browser_executor import BrowserExecutor
        from apa_sdk.testing import MockPage
        page = MockPage()
        page.title = "X"
        ex = BrowserExecutor("bot", SESSION, page=page, vision=BoomAdapter())
        ex.trigger_navigate("https://x.corp/")  # 不应抛异常
        assert ex.vision_fallbacks == 0


# --- Schema 录制模式（§B.1） --------------------------------------------------------
class TestSchemaRecorder:
    def test_record_and_draft_roundtrip(self, tmp_path):
        from apa_executors.browser_executor import BrowserExecutor
        from apa_sdk.recorder import SchemaRecorder
        from apa_sdk.semantic_adapter import SemanticAdapter
        from apa_sdk.testing import MockElement, MockPage

        recorder = SchemaRecorder(app_name="待办演示")
        page = MockPage()
        page.title = "待审批采购订单"
        page.elements = [
            __import__("apa_sdk.testing", fromlist=["MockElement"])
            and MockElement(role="heading", text="待审批采购订单"),
            MockElement(role="button", text="批准", data_apa_id="approve-btn"),
            MockElement(role="textbox", text="", data_apa_id="remark"),
        ]
        schema = SemanticAdapter({"semantic_patterns": {}})
        ex = BrowserExecutor("bot", SESSION, page=page,
                             adapter=schema, recorder=recorder)

        page.goto("https://erp.corp/po/pending")
        ex._execute_action("browser.navigate", {"url": "https://erp.corp/po/pending"})
        ex._execute_action("browser.click", {"target": "approve-btn"})
        ex._execute_action("browser.input",
                           {"target": "remark", "value": "同意"})

        draft_path = tmp_path / "schema.draft.yaml"
        recorder.save_draft(str(draft_path))
        text = draft_path.read_text(encoding="utf-8")
        assert "AUTO-GENERATED" in text and "TODO" in text  # 需人工审核标注

        # 草稿可被 SemanticAdapter 加载并匹配
        loaded = SemanticAdapter.from_yaml(str(draft_path))
        events = loaded.lift(page.screen_state())
        assert any(e.name == "browser.page.loaded" for e in events)
        s = recorder.summary()
        assert s["pages"] >= 1 and s["interactions"] == 2

    def test_click_records_element_trigger(self, tmp_path):
        from apa_executors.browser_executor import BrowserExecutor
        from apa_sdk.recorder import SchemaRecorder
        from apa_sdk.semantic_adapter import SemanticAdapter
        from apa_sdk.testing import MockElement, MockPage

        recorder = SchemaRecorder()
        page = MockPage()
        page.elements = [MockElement(role="button", text="批准",
                                     data_apa_id="approve-btn")]
        ex = BrowserExecutor("bot", SESSION, page=page,
                             adapter=SemanticAdapter(), recorder=recorder)
        page.goto("https://erp.corp/po/1")
        ex._execute_action("browser.click", {"target": "approve-btn"})
        draft = recorder.draft()
        interactions = [v for k, v in draft["semantic_patterns"].items()
                        if k.startswith("interaction")]
        assert len(interactions) == 1
        emit = interactions[0]["emit"]
        assert emit["trigger_element"]["role"] == "button"
        assert "批准" in emit["trigger_element"]["text_pattern"]
        assert emit["available_actions"][0]["maps_to_action"] == "browser.click"


# --- HashiCorp Vault KV v2 对接 ------------------------------------------------------
class _FakeVaultHandler(BaseHTTPRequestHandler):
    store: dict = {}

    def _authed(self) -> bool:
        return self.headers.get("X-Vault-Token") == "test-token"

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._authed():
            self._json(403, {"error": "permission denied"})
            return
        name = self.path.removeprefix("/v1/secret/data/")
        entry = type(self).store.get(name)
        if entry is None:
            self._json(404, {"error": "not found"})
        else:
            self._json(200, {"data": {"data": {"value": entry}}})

    def do_POST(self):
        if not self._authed():
            self._json(403, {"error": "permission denied"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        name = self.path.removeprefix("/v1/secret/data/")
        type(self).store[name] = body["data"]["value"]
        self._json(200, {"data": {"version": 1}})

    def do_DELETE(self):
        if not self._authed():
            self._json(403, {"error": "permission denied"})
            return
        name = self.path.removeprefix("/v1/secret/metadata/")
        type(self).store.pop(name, None)
        self._json(204, {})

    def do_LIST(self):
        if not self._authed():
            self._json(403, {"error": "permission denied"})
            return
        keys = sorted(type(self).store.keys())
        self._json(200, {"data": {"keys": keys}})

    def log_message(self, *a):
        pass


class TestHashiCorpVault:
    def test_kv2_crud_and_auth(self):
        _FakeVaultHandler.store.clear()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeVaultHandler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        backend = HashiCorpVaultBackend(addr=f"http://127.0.0.1:{port}",
                                        token="test-token")
        backend.put("erp/token", "hv-secret-7")
        assert backend.get("erp/token") == "hv-secret-7"
        assert "erp/token" in backend.list_names()
        assert backend.delete("erp/token")
        assert backend.get("erp/token") is None

        # 错误 token → 403 折叠为 VaultError
        bad = HashiCorpVaultBackend(addr=f"http://127.0.0.1:{port}",
                                    token="wrong")
        with pytest.raises(VaultError):
            bad.get("anything")

        httpd.shutdown()

    def test_missing_env_raises(self, monkeypatch):
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        with pytest.raises(VaultError):
            HashiCorpVaultBackend()