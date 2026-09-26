"""heuristic 决策契约：引擎诚实标注，不确定转人工。"""
import os
import unittest
from core import gateway
from core.decide import AUTO_THRESHOLD, decide, engine_name
from core.models import ReviewItem, new_id


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

    def test_fallback_never_auto_approves(self):
        """兜底引擎只准拦、不准放：放行置信度必须低于自动阈值，门控后转人工。

        降级不得放宽执行边界——红线是 auto_err=0，宁可多转人工。
        """
        d = decide(item("停水通知", "明早 8 点停水维护，请提前储水"))
        self.assertEqual(d.engine, "heuristic")
        self.assertLess(d.confidence, AUTO_THRESHOLD)
        final, via = gateway.route(d.action, d.confidence)
        self.assertEqual(final, "human.task.create")
        self.assertNotEqual(via, "auto")

    def test_fallback_may_still_auto_block(self):
        """兜底的拦截方向仍可自动执行：证据弱时拦截只花人工成本。"""
        d = decide(item("返利", "点击链接免费领取，刷单日结加微信"))
        self.assertEqual(d.engine, "heuristic")
        final, via = gateway.route(d.action, d.confidence)
        self.assertEqual((final, via), ("review.reject", "auto"))


if __name__ == "__main__":
    unittest.main()
