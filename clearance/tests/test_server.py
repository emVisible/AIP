"""server.py 端到端：起临时端口真服务，urllib 走完全链路。"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from clearance_core.server import make_handler
from clearance_core.store import ReviewStore
from http.server import ThreadingHTTPServer


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
        cls.tmp = tempfile.TemporaryDirectory()
        store = ReviewStore(cls.tmp.name)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

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

    def test_stats(self):
        code, body = _call("GET", self.url("/api/stats"))
        self.assertEqual(code, 200)
        self.assertIn("counts", body)


if __name__ == "__main__":
    unittest.main()
