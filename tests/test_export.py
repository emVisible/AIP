"""export 契约：已决议转标签，pending 跳过，meta 过凭据。"""
import json
import os
import tempfile
import unittest

from eval.export import clean_meta, export_samples


class TestExport(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            db = {
                "a1": {"item": {"kind": "article", "title": "t1", "body": "b1",
                                "meta": {"lang": "zh", "password": "x"}},
                       "state": "approved", "via": "auto"},
                "a2": {"item": {"kind": "comment", "title": "t2", "body": "b2",
                                "meta": {}},
                       "state": "rejected", "via": "policy_default",
                       "resolved_outcome": "reject"},
                "a3": {"item": {"kind": "comment", "title": "t3", "body": "b3",
                                "meta": {}},
                       "state": "pending"},
            }
            with open(os.path.join(d, "reviews.json"), "w", encoding="utf-8") as f:
                json.dump(db, f)
            rows, info = export_samples(d)
            self.assertEqual(info, {"pending": 1, "exported": 2})
            by_title = {r["title"]: r["expected"] for r in rows}
            self.assertEqual(by_title, {"t1": "approve", "t2": "reject"})
            m1 = next(r["meta"] for r in rows if r["title"] == "t1")
            self.assertEqual(m1, {"lang": "zh"})  # password 键被过滤

    def test_missing_db(self):
        with tempfile.TemporaryDirectory() as d:
            rows, info = export_samples(d)
            self.assertEqual((rows, info), ([], {"pending": 0, "exported": 0}))

    def test_clean_meta(self):
        self.assertEqual(clean_meta({"a": 1, "api_key": "x"}), {"a": 1})
        self.assertEqual(clean_meta("nope"), {})


if __name__ == "__main__":
    unittest.main()
