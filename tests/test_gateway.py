"""网关契约：幻觉动作拒绝、C4 凭据拦截、低置信转人工。"""
import unittest

from core import gateway


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


if __name__ == "__main__":
    unittest.main()
