"""macOS 原生桌面自动化引擎（Quartz CGEvent + AppKit + osascript）。

三层能力：
    Input    — Quartz CGEvent OS 级鼠标/键盘/滚动注入
    Perceive — 截图 + 窗口枚举 + 辅助功能元素树
    Control  — 应用激活/进程管理/剪贴板
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

try:
    import Quartz
    HAS_QUARTZ = True
except ImportError:
    Quartz = None
    HAS_QUARTZ = False


class KeyCode(IntEnum):
    RETURN = 36; TAB = 48; SPACE = 49; DELETE = 51; ESCAPE = 53
    COMMAND = 55; SHIFT = 56; CAPSLOCK = 57; OPTION = 58; CONTROL = 59
    LEFT_ARROW = 123; RIGHT_ARROW = 124; DOWN_ARROW = 125; UP_ARROW = 126

class MouseBtn(IntEnum):
    LEFT = 0; RIGHT = 1; MIDDLE = 2

MOD_FLAGS = {
    "cmd": 0x0010_0000,   # kCGEventFlagMaskCommand
    "shift": 0x0002_0000, # kCGEventFlagMaskShift
    "alt": 0x0008_0000,   # kCGEventFlagMaskAlternate
    "ctrl": 0x0004_0000,  # kCGEventFlagMaskControl
} if HAS_QUARTZ else {}


@dataclass
class WindowInfo:
    owner_name: str = ""
    window_name: str = ""
    pid: int = 0
    bounds: Dict[str, float] = field(default_factory=dict)


def _post(event) -> None:
    if HAS_QUARTZ:
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

def _mouse_ev(t: int, x: float, y: float, b: int = 0) -> Any:
    return Quartz.CGEventCreateMouseEvent(None, t, (x, y), b)

def _key_ev(kc: int, down: bool) -> Any:
    return Quartz.CGEventCreateKeyboardEvent(None, kc, down)

def _text_ev(text: str, down: bool) -> Any:
    ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
    Quartz.CGEventKeyboardSetUnicodeString(ev, len(text), text)
    return ev

def _sleep(ms: int) -> None:
    time.sleep(ms / 1000.0)


# ================================ 输入引擎 ================================
class InputEngine:
    """Quartz CGEvent 生产级输入引擎。"""

    def __init__(self, *, delay_ms: int = 30) -> None:
        self.delay_ms = delay_ms

    def _pause(self) -> None: time.sleep(self.delay_ms / 1000.0)

    def _post(self, ev) -> None: _post(ev)

    # ---- 鼠标 ----
    def move_mouse(self, x: int, y: int) -> None:
        _post(_mouse_ev(Quartz.kCGEventMouseMoved, x, y, 0))

    def click(self, x: int, y: int, *,
              button: MouseBtn = MouseBtn.LEFT, clicks: int = 1) -> None:
        self.move_mouse(x, y); _sleep(30)
        types = {
            MouseBtn.LEFT: (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp),
            MouseBtn.RIGHT: (Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp),
            MouseBtn.MIDDLE: (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp),
        }
        dt, ut = types[button]
        for _ in range(clicks):
            _post(_mouse_ev(dt, x, y, button)); _sleep(15)
            _post(_mouse_ev(ut, x, y, button)); _sleep(50)

    def double_click(self, x: int, y: int) -> None:
        self.click(x, y, clicks=2)

    def right_click(self, x: int, y: int) -> None:
        self.click(x, y, button=MouseBtn.RIGHT)

    def drag(self, fx: int, fy: int, tx: int, ty: int, *, ms: int = 300) -> None:
        self.move_mouse(fx, fy); _sleep(50)
        _post(_mouse_ev(Quartz.kCGEventLeftMouseDown, fx, fy, 0))
        steps = max(int(ms / 16), 2)
        for i in range(1, steps + 1):
            t = i / steps
            ix, iy = int(fx+(tx-fx)*t), int(fy+(ty-fy)*t)
            _post(_mouse_ev(Quartz.kCGEventLeftMouseDragged, ix, iy, 0))
            _sleep(ms // steps)
        _post(_mouse_ev(Quartz.kCGEventLeftMouseUp, tx, ty, 0))
        self._pause()

    def scroll(self, amount: int, **_) -> None:
        for _ in range(abs(amount)):
            d = 10 if amount > 0 else -10
            ev = Quartz.CGEventCreateScrollWheelEvent(
                None, Quartz.kCGScrollEventUnitByLine, 1, d)
            _post(ev); _sleep(20)

    # ---- 键盘 ----
    def type_text(self, text: str) -> None:
        """Unicode 字符串输入（支持中文）。"""
        for ch in text:
            _post(_text_ev(ch, True)); _sleep(3)
            _post(_text_ev(ch, False)); _sleep(3)
        self._pause()

    def press_key(self, keycode: int | str) -> None:
        code = getattr(KeyCode, str(keycode).upper(), keycode)
        down = _key_event(int(code), True)
        up = _key_event(int(code), False)
        _post(down); _sleep(15); _post(up)

    def hotkey(self, *keys: str) -> None:
        """组合键：hotkey("cmd", "c")。"""
        mod_flag = sum(MOD_FLAGS.get(k.lower(), 0) for k in keys
                       if k.lower() in MOD_FLAGS)
        key_codes: List[int] = []
        for k in keys:
            kl = k.lower()
            if kl in MOD_FLAGS:
                continue
            try:
                key_codes.append(KeyCode[kl.upper()].value)
            except KeyError:
                pass

        for m_flag in set(v for k, v in MOD_FLAGS.items()
                          if k in [x.lower() for x in keys]):
            ev = _key_event(0, True)
            if hasattr(Quartz, 'CGEventSetFlags'):
                Quartz.CGEventSetFlags(ev, m_flag)
            _post(ev)

        for kc in key_codes:
            down = _key_event(kc, True)
            up = _key_event(kc, False)
            _post(down); _sleep(15); _post(up)

        for m_flag in set(v for k, v in MOD_FLAGS.items()
                          if k in [x.lower() for x in keys]):
            ev = _key_event(0, False)
            if hasattr(Quartz, 'CGEventSetFlags'):
                Quartz.CGEventSetFlags(ev, m_flag)
            _post(ev)

    # ---- 感知 ----
    @staticmethod
    def screen_size() -> Tuple[int, int]:
        b = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        return int(b.size.width), int(b.size.height)

    @staticmethod
    def mouse_position() -> Tuple[float, float]:
        pos = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return pos.x, pos.y


# ================================ 窗口管理 ================================
class WindowManager:
    @staticmethod
    def list_windows() -> List[WindowInfo]:
        wl = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly |
            Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID)
        return [
            WindowInfo(
                owner_name=w.get("kCGWindowOwnerName", "?"),
                window_name=w.get("kCGWindowName", ""),
                pid=w.get("kCGWindowPID", 0),
                bounds=dict(w.get("kCGWindowBounds", {})),
            )
            for w in wl
        ]

    @staticmethod
    def activate(app_name: str) -> bool:
        r = subprocess.run(
            ["osascript", "-e",
             f'tell application "System Events" to '
             f'set frontmost of process "{app_name}" to true'],
            capture_output=True, text=True, timeout=10)
        return r.returncode == 0


# ================================ 剪贴板 ================================
class Clipboard:
    @staticmethod
    def copy(text: str) -> None:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)

    @staticmethod
    def paste_text() -> str:
        r = subprocess.run(["pbpaste"], capture_output=True, text=True)
        return r.stdout


# ================================ 截图 ================================
def screenshot(output_path: Optional[str] = None,
               region: Optional[Tuple[int,int,int,int]] = None) -> Optional[bytes]:
    cmd = ["screencapture", "-x"]
    if region:
        x, y, w, h = region
        cmd += ["-R", f"{x},{y},{w},{h}"]
    tmp = output_path or "/tmp/apa_screenshot.png"
    cmd.append(tmp)
    subprocess.run(cmd, timeout=15, check=True)
    with open(tmp, "rb") as f:
        return f.read()


# ---- 缺失导入修补 ----
import os  # noqa: E402
import threading  # noqa: E402