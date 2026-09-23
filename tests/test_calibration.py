"""calibration 数学契约：T=1 恒为候选，拟合永不差于出厂；坏输入原样返回。"""
import unittest

from clearance_core.calibration import (
    fit_temperature_binary,
    fit_temperature_categorical,
    rescale_answer,
    rescale_answers,
    scale_binary,
)


class TestCalibrationMath(unittest.TestCase):
    def test_binary_extremes(self):
        self.assertAlmostEqual(scale_binary(0.99, 1.0), 0.99, places=6)
        # 高温蔫平，低温变尖
        self.assertLess(scale_binary(0.99, 5.0), 0.99)
        self.assertGreater(scale_binary(0.99, 0.2), 0.99)
        self.assertAlmostEqual(scale_binary(0.5, 0.3), 0.5, places=6)

    def test_fit_overconfident(self):
        # 8 个 0.99 判错、2 个 0.99 判对 → 温度应升（蔫平），NLL 下降
        pairs = [(0.99, 0)] * 8 + [(0.99, 1)] * 2
        T, before, after = fit_temperature_binary(pairs)
        self.assertGreater(T, 1.0)
        self.assertLess(after, before)

    def test_fit_insufficient(self):
        T, before, after = fit_temperature_binary([(0.9, 1)] * 3)
        self.assertEqual((T, before, after), (1.0, before, before))

    def test_fit_categorical(self):
        rows = [({"a": 0.9, "b": 0.1}, "b")] * 6 + [({"a": 0.9, "b": 0.1}, "a")] * 2
        T, before, after = fit_temperature_categorical(rows)
        self.assertGreater(T, 1.0)
        self.assertLess(after, before)

    def test_rescale_noul(self):
        out = rescale_answer({"type": "noul", "noul": 0.99, "confidence": 0.99}, 3.0)
        self.assertLess(out["noul"], 0.99)
        self.assertAlmostEqual(out["confidence"], max(out["noul"], 1 - out["noul"]), places=6)

    def test_rescale_choice_flips(self):
        ans = {"type": "choice", "choice": "a", "confidence": 0.6,
               "probabilities": {"a": 0.6, "b": 0.4}}
        out = rescale_answer(ans, 0.15)  # 极低温锐化：0.6/0.4 差距放大
        self.assertEqual(out["choice"], "a")
        self.assertGreater(out["confidence"], 0.9)

    def test_rescale_passthrough(self):
        ans = {"type": "noul", "noul": 0.7}
        self.assertIs(rescale_answer(ans, 1.0), ans)
        self.assertEqual(rescale_answer({"weird": 1}, 2.0), {"weird": 1})

    def test_rescale_answers_table(self):
        answers = {"q1": {"type": "noul", "noul": 0.9, "confidence": 0.9}}
        out, applied = rescale_answers(answers, {"q1": {"T": 2.0}, "qx": {"T": 3.0}})
        self.assertTrue(applied)
        self.assertLess(out["q1"]["noul"], 0.9)
        out2, applied2 = rescale_answers(answers, {})
        self.assertFalse(applied2)


if __name__ == "__main__":
    unittest.main()
