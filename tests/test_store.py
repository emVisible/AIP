"""存储往返：submit → queue → resolve。"""
import tempfile
import unittest

from clearance_core.store import ReviewStore


class TestStore(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
