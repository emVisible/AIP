"""AX 元素识别引擎测试。

离线逻辑全平台可跑；live AX 测试在「darwin + 辅助功能已授权」时才执行。
"""
import sys

import pytest

from apa_executors import ax_engine as ax


class TestOffline:
    def test_import_without_frameworks_is_safe(self):
        """非 darwin（AS=None）时 API 优雅降级而非导入崩溃。"""
        if sys.platform == "darwin":
            pytest.skip("仅非 darwin 平台验证降级路径")
        assert ax.ax_trusted() is False
        assert ax.screen_capture_allowed() is False
        with pytest.raises(RuntimeError, match="ApplicationServices"):
            ax.systemwide()

    def test_permission_hints_present(self):
        assert "辅助功能" in ax.PERMISSION_HINTS["accessibility"]
        assert "屏幕录制" in ax.PERMISSION_HINTS["screen_capture"]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
@pytest.mark.skipif(not ax.ax_trusted(), reason="需要辅助功能权限")
class TestLiveAX:
    @pytest.fixture()
    def focused_target(self):
        """前台应用首个子元素（通常为主窗口）——确定性定位目标。"""
        import ApplicationServices as AS

        sw = ax.systemwide()
        err, app = AS.AXUIElementCopyAttributeValue(
            sw, "AXFocusedApplication", None)
        if err != 0 or app is None:
            pytest.skip("无前台应用")
        kids = ax._attr(app, "AXChildren") or []
        if not kids:
            pytest.skip("前台应用无子元素")
        return kids[0]

    def test_hit_test_returns_descriptor(self):
        import Quartz

        size = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()).size
        d = ax.hit_test(size.width / 2, size.height / 2)
        d.pop("_el", None)
        assert d["role"]
        assert d["bounds"] and all(k in d["bounds"] for k in ("x", "y", "w", "h"))
        assert isinstance(d["ax_path"], list)

    def test_hit_and_locate_roundtrip(self, focused_target):
        d = ax.describe(focused_target)
        el = ax.locate(d)
        assert el is not None
        d2 = ax.describe(el)
        assert d2["pid"] == d["pid"]

    def test_relocate_stability(self, focused_target):
        """同一描述符连续重定位 ≥8/10（确定性目标，不依赖屏幕布局）。"""
        d = ax.describe(focused_target)
        ok = sum(1 for _ in range(10) if ax.locate(d) is not None)
        assert ok >= 8, f"stability {ok}/10"

    def test_read_tree_limited(self):
        nodes = ax.read_tree(max_depth=2, max_nodes=50)
        assert len(nodes) <= 50
        assert all("role" in n for n in nodes)

    def test_press_dual_path(self, focused_target):
        clicked = []
        d = ax.describe(focused_target)
        r = ax.press(d, fallback_click=lambda x, y: clicked.append((x, y)))
        assert r["path_used"] in ("ax", "coord")
        if r["path_used"] == "coord":
            assert clicked, "coord fallback must invoke click"