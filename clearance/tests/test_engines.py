"""引擎插槽契约：注册/级联/跳过/未知拒绝；Jev 走本地 mock 服务。"""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from clearance_core.engines import (
    EngineUnavailable,
    availability,
    cascade,
    get,
    map_typed_answers,
    order,
)
from clearance_core.models import ReviewItem, new_id


def item(title, body, kind="comment", meta=None):
    return ReviewItem(new_id("t"), kind, title, body, meta or {})


class FakeJevHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode() or "{}")
        assert self.headers.get("Authorization", "").startswith("Bearer "), "要带 key"
        assert payload.get("model"), "要带 model"
        body = json.dumps({
            "model": "jev-mock-1.0",
            "answers": {
                "category": {"type": "choice", "choice": "normal",
                             "confidence": 0.9,
                             "probabilities": {"normal": 0.9, "other": 0.1}},
                "is_spam": {"type": "noul", "noul": 0.01},
                "toxic": {"type": "noul", "noul": 0.01},
                "fraud": {"type": "noul", "noul": 0.01},
                "sensitive": {"type": "noul", "noul": 0.01},
                "severity": {"type": "score", "score": 0.1,
                             "probabilities": {"0": 0.9, "1": 0.1, "2": 0.0}},
            },
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestEngines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = {k: os.environ.get(k) for k in
                    ("ENGINE_ORDER", "LAYA_SIDECAR_URL", "TYPESAFE_API_KEY",
                     "JEV_API_URL", "JEV_MODEL")}
        os.environ["LAYA_SIDECAR_URL"] = "http://127.0.0.1:1"  # 隔离真 sidecar
        os.environ.pop("TYPESAFE_API_KEY", None)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeJevHandler)
        cls.jev_port = srv.server_address[1]
        cls.srv = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_registry_and_order(self):
        self.assertEqual(set(["rules", "laya:sidecar", "jev", "heuristic"]),
                         set(order()))
        for name in order():
            self.assertEqual(get(name).name, name)

    def test_unknown_engine(self):
        with self.assertRaises(ValueError):
            get("nope")

    def test_rules_hit_and_abstain(self):
        d = get("rules").decide(item("求助", "密码是xxx"))
        self.assertEqual(d.action, "human.task.create")
        self.assertIsNone(get("rules").decide(item("你好", "明早停水")))

    def test_cascade_falls_to_heuristic(self):
        d = cascade(item("返利", "点击链接免费领取刷单"))
        self.assertEqual((d.action, d.engine), ("review.reject", "heuristic"))

    def test_cascade_rules_first(self):
        d = cascade(item("申诉", "密码是xxx"))
        self.assertEqual((d.action, d.engine), ("human.task.create", "rules"))

    def test_cascade_skips_down_engines(self):
        d = cascade(item("停水", "明早8点停水"))
        self.assertEqual(d.engine, "heuristic")
        self.assertTrue(any("laya:sidecar" in r and "jev" in r for r in d.reasons)
                        or any("skipped" in r for r in d.reasons))

    def test_jev_no_key_skips(self):
        with self.assertRaises(EngineUnavailable):
            get("jev").decide(item("t", "b"))

    def test_jev_mock_maps_and_bills(self):
        os.environ["TYPESAFE_API_KEY"] = "test-key"
        os.environ["JEV_API_URL"] = f"http://127.0.0.1:{self.jev_port}"
        try:
            d = get("jev").decide(item("通知", "明早停水维护"))
        finally:
            os.environ.pop("TYPESAFE_API_KEY", None)
            os.environ.pop("JEV_API_URL", None)
        self.assertEqual((d.action, d.engine), ("review.approve", "jev"))
        self.assertEqual(d.usage, {"input_tokens": 100, "output_tokens": 20})
        self.assertEqual(d.route_model, "jev-mock-1.0")

    def test_map_shared(self):
        ans = {"category": {"type": "choice", "choice": "x", "confidence": 0.1,
                            "probabilities": {"x": 0.1}},
               "is_spam": {"type": "noul", "noul": 0.99},
               "toxic": {"type": "noul", "noul": 0.0},
               "fraud": {"type": "noul", "noul": 0.0},
               "sensitive": {"type": "noul", "noul": 0.0},
               "severity": {"type": "score", "score": 1.0,
                            "probabilities": {"0": 0.0, "1": 1.0, "2": 0.0}}}
        d = map_typed_answers(ans, engine="x-engine")
        self.assertEqual((d.action, d.engine), ("review.reject", "x-engine"))

    def test_availability_shape(self):
        a = availability()
        self.assertIn("heuristic", a["available"])
        self.assertIn(a["primary"], ("laya:sidecar", "jev", "heuristic"))


if __name__ == "__main__":
    unittest.main()
