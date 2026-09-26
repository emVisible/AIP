"""网关契约：幻觉动作拒绝、C4 凭据拦截、低置信转人工。"""
import unittest
from dataclasses import fields

from core import gateway
from core.models import Decision


class TestGateway(unittest.TestCase):
    def test_unknown_action_rejected(self):
        ok, reason = gateway.validate_action("browser.click", {})
        self.assertFalse(ok)
        self.assertIn("action_not_registered", reason)

    def test_credential_blocked(self):
        ok, reason = gateway.validate_action("notify.send", {"body": "password=abc"})
        self.assertFalse(ok)
        self.assertIn("credential_in_payload", reason)

    def test_oversize_blocked(self):
        ok, reason = gateway.validate_action("notify.send", {"body": "x" * 5000})
        self.assertFalse(ok)
        self.assertIn("payload_too_large", reason)

    def test_low_confidence_to_human(self):
        action, _ = gateway.route("review.approve", 0.5)
        self.assertEqual(action, "human.task.create")

    def test_high_confidence_auto(self):
        action, via = gateway.route("review.approve", 0.9)
        self.assertEqual((action, via), ("review.approve", "auto"))

    def test_registry_only_seven(self):
        self.assertEqual(len(gateway.REGISTRY), 7)

    def test_risk_declared_only_in_registry(self):
        """C3：risk/幂等是「能力」的属性，唯一权威是注册表。

        Decision 曾自带 risk 字段，与注册表同语义不同值（approve 报 L1、
        注册表 L2）——两处声明同一语义即会在第一次修改时分叉。
        """
        self.assertNotIn("risk", {f.name for f in fields(Decision)})
        for name, meta in gateway.REGISTRY.items():
            self.assertIn(meta.get("risk"), ("L0", "L1", "L2"), name)
            self.assertEqual(meta.get("idempotency"), "required", name)


if __name__ == "__main__":
    unittest.main()
