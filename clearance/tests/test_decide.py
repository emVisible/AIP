"""heuristic 决策契约：引擎诚实标注，不确定转人工。"""
import os
import unittest
from clearance_core.decide import decide, engine_name
from clearance_core.models import ReviewItem, new_id


def item(title, body, kind="comment"):
    return ReviewItem(new_id("t"), kind, title, body)


class TestDecide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 强制走 heuristic：测试不依赖 sidecar 是否在跑
        cls._old = os.environ.get("LAYA_SIDECAR_URL")
        os.environ["LAYA_SIDECAR_URL"] = "http://127.0.0.1:1"

    @classmethod
    def tearDownClass(cls):
        if cls._old is None:
            os.environ.pop("LAYA_SIDECAR_URL", None)
        else:
            os.environ["LAYA_SIDECAR_URL"] = cls._old

    def test_engine_label(self):
        self.assertIn(engine_name(), ("laya:sidecar", "laya", "heuristic"))

    def test_spam_rejected(self):
        d = decide(item("返利", "点击链接免费领取，刷单日结加微信"))
        self.assertEqual(d.action, "review.reject")
        self.assertGreaterEqual(d.confidence, 0.85)

    def test_fraud_rejected(self):
        d = decide(item("申诉", "银行转账验证码，保证金解冻费"))
        self.assertEqual(d.action, "review.reject")

    def test_sensitive_to_human(self):
        d = decide(item("求助", "我的密码是 123456，请帮忙"))
        self.assertEqual(d.action, "human.task.create")

    def test_clean_approved(self):
        d = decide(item("停水通知", "明早 8 点停水维护，请提前储水"))
        self.assertEqual(d.action, "review.approve")


if __name__ == "__main__":
    unittest.main()
