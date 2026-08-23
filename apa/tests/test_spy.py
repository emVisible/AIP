"""桌面拾取器测试（合成事件注入，不依赖真实鼠标移动）。"""
import json

import pytest

from apa_core.spy import SpyError, SpyService, spy_stream_frames


@pytest.fixture()
def spy():
    return SpyService()


class TestThrottleAndCapture:
    def test_version_bumps_on_move(self, spy):
        import Quartz

        pt = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        v0 = spy.status()["version"]
        spy.on_mouse_move(pt.x, pt.y)
        assert spy.status()["version"] == v0 + 1

    def test_throttle_same_spot(self, spy):
        import Quartz

        pt = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        spy.on_mouse_move(pt.x, pt.y)
        v = spy.status()["version"]
        for _ in range(5):  # 同位置连发 → 节流
            spy.on_mouse_move(pt.x, pt.y)
        assert spy.status()["version"] == v

    def test_capture_without_hover_raises(self, monkeypatch):
        """无 hover 缓存时 capture 报错。"""
        s = SpyService()
        monkeypatch.setattr(s, "current", lambda: None)
        with pytest.raises(SpyError):
            s.capture()

    def test_latest_descriptor_shape(self, spy):
        import Quartz

        pt = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        spy.on_mouse_move(pt.x, pt.y)
        d = spy.current()
        assert d is not None
        for k in ("role", "pid", "ax_path", "bounds"):
            assert k in d
        assert "_el" not in d, "序列化面不得泄漏 AX 句柄"


class TestStreamFrames:
    def test_hover_frame_on_change(self, spy):
        import Quartz

        pt = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        spy.on_mouse_move(pt.x, pt.y)
        gen = spy_stream_frames(spy, poll_interval=0.01)
        frame = json.loads(next(gen))
        assert frame["type"] == "hover"
        assert frame["version"] >= 1
        gen.close()

    def test_ended_frame_when_stopped(self, spy):
        import Quartz

        pt = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        spy.on_mouse_move(pt.x, pt.y)
        spy.stop()
        gen = spy_stream_frames(spy, poll_interval=0.01)
        frames = [json.loads(next(gen))]
        try:
            while True:
                f = json.loads(next(gen))
                frames.append(f)
                if f["type"] == "ended":
                    break
        except StopIteration:
            pass
        assert frames[-1]["type"] == "ended"


class TestLifecycle:
    def test_status_shape(self, spy):
        st = spy.status()
        assert {"active", "version", "latest"} <= set(st)

    @pytest.mark.skipif(
        not __import__("apa_executors.ax_engine", fromlist=["ax"])
        .ax_trusted(),
        reason="需要辅助功能权限")
    def test_real_eventtap_session(self):
        import time

        s = SpyService()
        s.start()
        time.sleep(1.2)
        try:
            assert s.status()["active"], s.last_error
        finally:
            r = s.stop()
        assert r["stopped"] is True
        assert not s.status()["active"]