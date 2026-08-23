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