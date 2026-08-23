"""OCR 执行器测试：mock 后端 + http_ocr 本地存根。"""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from apa_executors.ocr_executor import OCRExecutor


def _exec():
    ex = OCRExecutor.__new__(OCRExecutor)
    ex.vault = None
    return ex


class TestMock:
    def test_mock_returns_text(self, tmp_path):
        img = tmp_path / "scan.png"
        img.write_bytes(b"\x89PNG fake")
        ok, out = _exec()._execute_action(
            "ocr.extract", {"backend": "mock", "image_path": str(img)})
        assert ok
        assert "mock-ocr" in out["text"]
        assert "scan.png" in out["text"]

    def test_unknown_backend(self):
        ok, err = _exec()._execute_action(
            "ocr.extract", {"backend": "tesseract9"})
        assert not ok
        assert "unknown backend" in err["code"]

    def test_unsupported_action(self):
        ok, err = _exec()._execute_action("ocr.translate", {})
        assert not ok


class TestHttpOcr:
    @pytest.fixture()
    def ocr_stub(self):
        """本地 OCR API 存根：校验请求头与 payload，返回 {text}。"""
        seen: dict = {}

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n))
                seen["headers"] = dict(self.headers)
                seen["payload"] = body
                out = {"text": f"识别到:{body['language']}"}
                resp = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        yield srv.server_address[1], seen
        srv.shutdown()

    def test_http_roundtrip(self, ocr_stub, tmp_path):
        port, seen = ocr_stub
        img = tmp_path / "doc.png"
        img.write_bytes(b"fake-image-bytes")

        ok, out = _exec()._execute_action("ocr.extract", {
            "backend": "http_ocr",
            "endpoint": f"http://127.0.0.1:{port}/v1/ocr",
            "image_path": str(img),
            "language": "chs",
            "auth": {"env": "APA_TEST_OCR_KEY"},
            "headers": {},
        })
        # 无 vault 时 auth 被忽略，但请求本身应成功
        assert ok, out
        assert out["text"] == "识别到:chs"

        sent = seen["payload"]
        decoded = base64.b64decode(sent["image_b64"])
        assert decoded == b"fake-image-bytes"
        assert sent["language"] == "chs"

    def test_inline_b64(self, ocr_stub):
        port, _ = ocr_stub
        raw = base64.b64encode(b"inline").decode()
        ok, out = _exec()._execute_action("ocr.extract", {
            "backend": "http_ocr",
            "endpoint": f"http://127.0.0.1:{port}/v1/ocr",
            "image_b64": raw,
        })
        assert ok and out["text"].startswith("识别到")

    def test_missing_image_input(self, ocr_stub):
        port, _ = ocr_stub
        ok, err = _exec()._execute_action("ocr.extract", {
            "backend": "http_ocr",
            "endpoint": f"http://127.0.0.1:{port}/v1/ocr",
        })
        assert not ok