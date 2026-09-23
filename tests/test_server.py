"""server.py 端到端：起临时端口真服务，urllib 走完全链路。"""
import http.client
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from clearance_core.server import EventHub, make_handler
from clearance_core.store import ReviewStore
from http.server import ThreadingHTTPServer
import http.client


def _call(method, url, payload=None):
    data = json.dumps(payload or {}).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 强制走 heuristic：测试不依赖 sidecar 是否在跑
        cls._old = os.environ.get("LAYA_SIDECAR_URL")
        os.environ["LAYA_SIDECAR_URL"] = "http://127.0.0.1:1"
        cls.tmp = tempfile.TemporaryDirectory()
        store = ReviewStore(cls.tmp.name)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0),
                                      make_handler(store, EventHub()))
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()
        if cls._old is None:
            os.environ.pop("LAYA_SIDECAR_URL", None)
        else:
            os.environ["LAYA_SIDECAR_URL"] = cls._old

    def url(self, p):
        return f"http://127.0.0.1:{self.port}{p}"

    def test_health(self):
        code, body = _call("GET", self.url("/api/health"))
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])

    def test_submit_queue_resolve(self):
        code, body = _call("POST", self.url("/api/review/submit"),
                           {"kind": "comment", "title": "返利",
                            "body": "点击链接免费领取刷单"})
        self.assertEqual(code, 200)
        self.assertEqual(body["state"], "rejected")

        code, body = _call("POST", self.url("/api/review/submit"),
                           {"kind": "article", "title": "申诉", "body": "密码是xxx"})
        rid = body["item"]["id"]
        self.assertEqual(body["state"], "pending")

        code, body = _call("GET", self.url("/api/queue?state=pending"))
        self.assertTrue(any(i["item"]["id"] == rid for i in body["items"]))

        code, body = _call("POST", self.url(f"/api/review/{rid}/resolve"),
                           {"outcome": "approve", "actor": "admin"})
        self.assertEqual(body["state"], "approved")

        code, _ = _call("POST", self.url("/api/review/rev_missing/resolve"),
                        {"outcome": "approve"})
        self.assertEqual(code, 404)

    def test_context_get_roundtrip(self):
        import os as _os
        _os.environ["COD_BLOB_THRESHOLD"] = "10"
        try:
            code, body = _call("POST", self.url("/api/review/submit"),
                               {"kind": "article", "title": "长文",
                                "body": "正文内容。正文内容。正文内容。"})
            self.assertEqual(code, 200)
            ref = body["item"]["body_ref"]
            self.assertTrue(ref)
            self.assertEqual(body["item"]["body"], "")
            code, out = _call("POST", self.url("/api/context/get"),
                              {"ref": ref, "fields": ["body"]})
            self.assertEqual(code, 200)
            self.assertIn("正文内容", out["data"]["body"])
            code, _ = _call("POST", self.url("/api/context/get"),
                            {"ref": ref, "fields": ["*"]})
            self.assertEqual(code, 400)
            code, _ = _call("POST", self.url("/api/context/get"),
                            {"ref": "ctx_nope.body", "fields": ["body"]})
            self.assertEqual(code, 404)
        finally:
            _os.environ.pop("COD_BLOB_THRESHOLD", None)

    def test_stats(self):
        code, body = _call("GET", self.url("/api/stats"))
        self.assertEqual(code, 200)
        self.assertIn("counts", body)

    def test_health_has_sidecar_field(self):
        code, body = _call("GET", self.url("/api/health"))
        self.assertEqual(code, 200)
        self.assertIn("sidecar", body)  # 无 sidecar 时为 None，在场时为明细

    def test_sse_hello_then_submit(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn("text/event-stream", resp.getheader("Content-Type"))

        def read_event():
            etype, data = "", ""
            while True:
                line = resp.readline().decode().strip()
                if line.startswith("event:"):
                    etype = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    return etype, json.loads(data)
                elif line == "" and etype:
                    continue

        etype, hello = read_event()
        self.assertEqual(etype, "hello")
        self.assertIn("counts", hello)

        code, created = _call("POST", self.url("/api/review/submit"),
                              {"kind": "article", "title": "t", "body": "明早停水"})
        self.assertEqual(code, 200)
        seq = [read_event()[0] for _ in range(4)]
        self.assertEqual(seq, ["accepted", "running", "terminal", "submitted"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
