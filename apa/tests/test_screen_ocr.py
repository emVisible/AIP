"""Vision OCR 测试：离线确定性渲染图（不依赖屏幕录制权限）。"""
import sys

import pytest

from apa_executors import screen_ocr as so

def vision_available() -> bool:
    try:
        import Vision  # noqa: F401
        import Quartz  # noqa: F401

        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (sys.platform == "darwin" and vision_available()),
    reason="需要 macOS + pyobjc-Vision/Quartz",
)


MARKER = "APA-OCR-2026"


@pytest.fixture(scope="module")
def rendered():
    return so.render_text_image(MARKER, width=640, height=180,
                                font_size=48.0)


class TestOfflineOCR:
    def test_recognizes_marker(self, rendered):
        hits = so.ocr_image(rendered)
        joined = " ".join(h["text"] for h in hits)
        assert "APA" in joined, hits

    def test_bounds_within_canvas(self, rendered):
        for h in so.ocr_image(rendered):
            b = h["bounds"]
            assert 0 <= b["x"] and b["w"] > 0
            assert b["x"] + b["w"] <= 700   # 允许少量溢出
            assert 0 <= b["y"] and b["h"] > 0
            assert b["y"] + b["h"] <= 220

    def test_confidence_range(self, rendered):
        for h in so.ocr_image(rendered):
            assert 0.0 < h["confidence"] <= 1.0

    def test_image_level_locate(self, rendered):
        """图像级包含匹配（不经屏幕截取）。"""
        hits = so.ocr_image(rendered)
        best = max((h for h in hits if "2026" in h["text"]),
                   key=lambda h: h["confidence"], default=None)
        assert best is not None
        assert best["bounds"]["w"] > 10

    def test_chinese_render_and_recognize(self):
        img = so.render_text_image("订单审批通过", font_size=56.0)
        hits = so.ocr_image(img)
        joined = "".join(h["text"] for h in hits).replace(" ", "")
        assert any(ch in joined for ch in ("订单", "审批", "通")), hits

class TestWaitText:
    def test_found_on_second_poll(self, monkeypatch):
        from apa_executors.ocr_executor import OCRExecutor

        ex = OCRExecutor.__new__(OCRExecutor)
        seq = [None, {"bounds": {"x": 1, "y": 2, "w": 3, "h": 4},
                      "text": "就绪", "confidence": 0.9}]
        calls = []

        def fake_locate(target, **kw):
            calls.append(target)
            return seq[len(calls) - 1] if len(calls) <= len(seq) else None

        from apa_executors import screen_ocr as so
        import apa_executors.ocr_executor as oe
        import time as _t

        monkeypatch.setattr(so, "locate_text", fake_locate)
        monkeypatch.setattr(_t, "sleep", lambda s: None)

        ok, out = ex._execute_action("ocr.wait_text",
                                     {"text": "就绪", "interval_s": 0.01,
                                      "timeout_s": 5})
        assert ok and out["found"] and out["bounds"]["w"] == 3
        assert calls == ["就绪", "就绪"]

    def test_timeout_returns_text_timeout(self, monkeypatch):
        from apa_executors.ocr_executor import OCRExecutor

        ex = OCRExecutor.__new__(OCRExecutor)
        from apa_executors import screen_ocr as so
        import apa_executors.ocr_executor as oe
        import time as _t

        monkeypatch.setattr(so, "locate_text", lambda t, **kw: None)
        # monotonic 加速流逝：每次读取 +0.2s
        base = {"v": _t.monotonic()}

        def fast_mono():
            base["v"] += 0.2
            return base["v"]
        monkeypatch.setattr(oe._t, "monotonic", fast_mono)
        monkeypatch.setattr(_t, "sleep", lambda s: None)

        ok, err = ex._execute_action("ocr.wait_text",
                                     {"text": "不存在", "timeout_s": 1,
                                      "interval_s": 0.1})
        assert not ok and err["code"] == "text_timeout"
