"""apa-core: 桌面拾取器服务（影刀 Ctrl 悬停体验 · M2）。

架构：
  Quartz EventTap（listen-only）监听鼠标移动
    → 节流 AX hit-test（位移阈值 + 时间窗）
    → latest 描述符缓存 + 版本号递增
  SSE /api/spy/stream 消费版本变化推送 hover 元素

设计约束：
  - EventTap 线程独立 CFRunLoop，stop 时可从外部终止
  - hit-test 失败静默（悬停到无 AX 内容区域属正常）
  - 测试可注入合成鼠标事件，不依赖真实 EventTap/权限
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

try:
    from apa_executors import ax_engine as ax
except Exception:  # pragma: no cover
    ax = None  # type: ignore


class SpyError(RuntimeError):
    pass


def _ax_module():
    """惰性获取 ax_engine；缺失返回 None（非 darwin/未装框架）。"""
    try:
        from apa_executors import ax_engine as _ax
        return _ax
    except Exception:  # noqa: BLE001
        return None


def ensure_accessibility() -> None:
    """辅助功能权限预检（H3 自 api.py 下沉至服务层）。

    未授权时触发系统原生授权弹窗并抛 SpyError（HTTP 层映射 409）。
    """
    ax = _ax_module()
    if ax is None or ax.ax_trusted():
        return
    hint = str(getattr(ax, "PERMISSION_HINTS", {}).get(
        "accessibility", "系统设置 → 隐私与安全性 → 辅助功能"))
    try:
        import ApplicationServices as _AS

        _AS.AXIsProcessTrustedWithOptions(
            {_AS.kAXTrustedCheckOptionPrompt: True})
    except Exception:  # noqa: BLE001
        pass
    raise SpyError(
        f"缺少 macOS「辅助功能」权限：{hint}。授权后重启 APA 生效。")


class SpyService:
    """桌面元素拾取会话。进程内单例由 API 层持有。"""

    def __init__(self, *,
                 move_threshold_px: float = 6.0,
                 min_interval_s: float = 0.08,
                 max_fps: int = 20) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._tap = None
        self._running = False

        # 节流参数
        self._threshold = float(move_threshold_px)
        self._min_interval = float(min_interval_s)
        self._last_xy: Optional[tuple] = None
        self._last_test_t = 0.0

        # 最新 hover 结果（SSE 消费）
        self._latest: Optional[Dict[str, Any]] = None
        self._version = 0
        self.started_at = 0.0
        self.last_error: Optional[str] = None

    # ---- 状态 ---------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active": self._running,
                "version": self._version,
                "latest": self._latest,
                "error": self.last_error,
            }

    def current(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._latest) if self._latest else None

    # ---- 生命周期 -----------------------------------------------------------

    def start(self) -> Dict[str, Any]:
        if ax is None:
            raise SpyError("ax_engine unavailable (darwin + pyobjc required)")
        with self._lock:
            if self._running:
                return {"session": "already_running"}
            self._running = True
            self.started_at = time.time()
        t = threading.Thread(target=self._run_loop, daemon=True,
                             name="apa-spy-eventtap")
        self._thread = t
        t.start()
        return {"session": "started"}

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            was = self._running
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self._tap = None
        return {"stopped": was}

    def _run_loop(self) -> None:
        """EventTap 安装 + 本线程 RunLoop 驱动；每 0.5s 检查停止信号。"""
        try:
            self._install_eventtap()
            from CoreFoundation import (
                CFRunLoopGetCurrent, CFRunLoopRunInMode, kCFRunLoopDefaultMode,
            )

            rl = CFRunLoopGetCurrent()
            self._rl = rl
            while self._running:
                # 带超时运行：周期性返回以便检查停止标志
                CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.5, False)
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self.last_error = f"{type(e).__name__}: {e}"
        finally:
            with self._lock:
                self._running = False

    def _install_eventtap(self) -> None:
        import Quartz
        from CoreFoundation import (
            CFMachPortCreateRunLoopSource, CFRunLoopAddSource,
            CFRunLoopGetCurrent, kCFRunLoopCommonModes,
        )

        def callback(_proxy, _etype, event, _ctx):
            try:
                pt = Quartz.CGEventGetLocation(event)
                self.on_mouse_move(pt.x, pt.y)
            except Exception:
                pass
            return event

        mask = (Quartz.CGEventMaskBit(Quartz.kCGEventMouseMoved) |
                Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDragged))
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            callback,
            None,
        )
        if tap is None:
            raise RuntimeError(
                "CGEventTapCreate failed — "
                f"{ax.PERMISSION_HINTS['accessibility']}")
        src = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        self._tap = tap
        # run loop 由调用线程进入；保存 source 以便 stop 停止
        self._rl_source = src
        self._callback_ref = callback  # 防 GC

    # ---- 事件处理（可注入测试） ----------------------------------------------

    def on_mouse_move(self, x: float, y: float) -> None:
        """节流后的命中测试入口。测试可直接调用注入坐标。"""
        now = time.monotonic()
        if self._last_xy is not None:
            dx = x - self._last_xy[0]
            dy = y - self._last_xy[1]
            moved2 = dx * dx + dy * dy
            if moved2 < self._threshold * self._threshold and \
               (now - self._last_test_t) < self._min_interval:
                return
        self._last_xy = (x, y)
        self._last_test_t = now

        try:
            d = ax.hit_test(float(x), float(y))
            d.pop("_el", None)
        except Exception:
            d = None

        with self._lock:
            if d is None:
                self._latest = None
            else:
                self._latest = d
            self._version += 1

    def capture(self) -> Dict[str, Any]:
        """取当前 hover 元素作为「已捕获」描述符。"""
        cur = self.current()
        if cur is None:
            raise SpyError("nothing under cursor")
        return {"element": cur}


# ---------------------------------------------------------------------------
# SSE 流辅助：把版本号变化转成事件帧
# ---------------------------------------------------------------------------

def spy_stream_frames(spy: SpyService, *,
                      poll_interval: float = 0.1,
                      heartbeat_every: int = 300,
                      max_seconds: float = 600.0):
    """生成器：yield JSON 行字符串。版本未变时定期心跳防断连。"""
    import json

    last_seen = -1
    last_err: Optional[str] = None
    ticks = 0
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        st = spy.status()
        # 错误帧：EventTap 线程失败等场景推给前端，避免假死
        err = st.get("error")
        if err and err != last_err:
            last_err = err
            yield json.dumps({"type": "error", "message": err},
                             ensure_ascii=False) + "\n"
        if st["version"] != last_seen:
            last_seen = st["version"]
            frame = {
                "type": "hover",
                "version": st["version"],
                "element": st["latest"],
            }
            yield json.dumps(frame, ensure_ascii=False) + "\n"
        elif st.get("active") is False and last_seen >= 0:
            yield json.dumps({"type": "ended"}) + "\n"
            return
        else:
            ticks += 1
            if ticks % heartbeat_every == 0:
                yield ": hb\n\n"
        time.sleep(poll_interval)
    yield json.dumps({"type": "timeout"}) + "\n"