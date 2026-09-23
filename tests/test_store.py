"""存储往返：submit → queue → resolve。"""
import tempfile
import unittest

from core.store import ReviewStore


class TestStore(unittest.TestCase):
    def test_progress_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            s = ReviewStore(d)
            seen = []
            rec = s.submit("article", "t", "明早停水",
                           {}, on_progress=lambda t, p: seen.append((t, p["id"])))
            self.assertEqual([t for t, _ in seen], ["accepted", "running", "terminal"])
            self.assertTrue(all(pid == rec.item.id for _, pid in seen))
            stored = [r for r in s.queue("") if r["item"]["id"] == rec.item.id][0]
            self.assertEqual(stored["progress"], ["accepted", "running", "terminal"])
            self.assertGreater(stored["terminal_at"], 0)

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            s = ReviewStore(d)
            rec = s.submit("article", "停水通知", "明早停水维护", {})
            self.assertIn(rec.state, ("approved", "rejected", "pending"))
            if rec.state == "pending":
                out = s.resolve(rec.item.id, "approve", "admin")
                self.assertEqual(out["state"], "approved")
                self.assertRaises(ValueError, s.resolve, rec.item.id, "approve", "admin")
            self.assertRaises(KeyError, s.resolve, "rev_missing", "approve", "admin")

    def test_spam_end_to_end_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            s = ReviewStore(d)
            rec = s.submit("comment", "返利", "点击链接免费领取刷单", {})
            self.assertEqual(rec.state, "rejected")

    def test_blob_spill_and_context_get(self):
        import os as _os
        _os.environ["COD_BLOB_THRESHOLD"] = "20"
        try:
            with tempfile.TemporaryDirectory() as d:
                s = ReviewStore(d)
                big = "正文内容。" * 50
                rec = s.submit("article", "长文", big, {})
                stored = [r for r in s.queue("") if r["item"]["id"] == rec.item.id][0]
                self.assertEqual(stored["item"]["body"], "")
                ref = stored["item"]["body_ref"]
                self.assertTrue(ref.startswith("ctx_"))
                # 决策看的是全文（不断言具体引擎，只断言链路不断）
                self.assertIn(stored["decision"]["engine"],
                              ("heuristic", "rules", "laya:sidecar"))
                out = s.context_get(ref, ["body"])
                self.assertEqual(out["data"]["body"], big)
                with self.assertRaises(ValueError):
                    s.context_get(ref, ["*"])
                with self.assertRaises(ValueError):
                    s.context_get(ref, ["nope"])
                with self.assertRaises(ValueError):
                    s.context_get("../../etc/passwd", ["body"])
                with self.assertRaises(OSError):
                    s.context_get("ctx_missing.body", ["body"])
        finally:
            _os.environ.pop("COD_BLOB_THRESHOLD", None)

    def test_small_body_stays_inline(self):
        with tempfile.TemporaryDirectory() as d:
            s = ReviewStore(d)
            rec = s.submit("article", "t", "短正文", {})
            stored = [r for r in s.queue("") if r["item"]["id"] == rec.item.id][0]
            self.assertEqual(stored["item"]["body"], "短正文")
            self.assertEqual(stored["item"]["body_ref"], "")


if __name__ == "__main__":
    unittest.main()
