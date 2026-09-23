"""heuristic 决策契约：引擎诚实标注，不确定转人工。"""
import unittest

from clearance_core.decide import decide, engine_name
from clearance_core.models import ReviewItem, new_id


def item(title, body, kind="comment"):
    return ReviewItem(new_id("t"), kind, title, body)


class TestDecide(unittest.TestCase):
    def test_engine_label(self):
        self.assertIn(engine_name(), ("laya", "heuristic"))

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
