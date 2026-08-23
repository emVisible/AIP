"""macOS 原生桌面自动化引擎（Quartz CGEvent + AppKit）。

生产级输入模拟：鼠标/键盘/滚动，OS 级事件注入。
依赖：pyobjc-framework-Quartz, pyobjc-framework-Cocoa（uv 安装）。

设计原则：
  · 每个方法 = 一个原子操作（可被 ProcessEngine 编排）
  · 所有坐标为屏幕绝对坐标（Retina 下自动转换逻辑坐标）
  · 输入前后可插入验证钩子（observe→act→verify 状态机）
"""
from __future__ import annotations

import ctypes
import ctypes.util
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

# ---- 虚拟键码表 ----
class KeyCode(IntEnum):
    RETURN = 36
    TAB = 48
    SPACE = 49
    DELETE = 51
    ESCAPE = 53
    COMMAND = 55
    SHIFT = 56
    CAPSLOCK = 57
    OPTION = 58
    CONTROL = 59
    LEFT_ARROW = 123
    RIGHT_ARROW = 124
    DOWN_ARROW = 125
    UP_ARROW = 126
    FORWARD_DELETE = 117

class MouseBtn(IntEnum):
    LEFT = 0
    RIGHT = 1
    MIDDLE = 2

# 修饰键掩码
MOD_FLAGS = {
    "cmd": Quartz.kCGEventFlagMaskCommand,
    "shift": Quartz.kCGEventFlagMaskShift,
    "alt": Quartz.kCGEventFlagMaskAlternate,
    "ctrl": Quartz.kCGEventFlagMaskControl,
} if HAS_QUARTZ else {}


@dataclass
class WindowInfo:
    owner_name: str = ""
    window_name: str = ""
    pid: int = 0
    layer: int = 0
    bounds: Dict[str, float] = field(default_factory=dict)


@dataclass
class ElementTarget:
    """元素定位策略（优先级从上到下尝试）。"""
    accessibility_id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    app_name: Optional[str] = None
    window_title: Optional[str] = None


def _post(event) -> None:
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def _mouse_event(etype: int, x: float, y: float, btn: int = 0) -> Any:
    return Quartz.CGEventCreateMouseEvent(
        None, etype, (x, y), btn)


def _key_event(keycode: int, down: bool) -> Any:
    return Quartz.CGEventCreateKeyboardEvent(None, keycode, down)


def _unicode_event(text: str, down: bool) -> Any:
    ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
    Quartz.CGEventKeyboardSetUnicodeString(ev, len(text), text)
    return ev


def _sleep_ms(ms: int) -> None:
    time.sleep(ms / 1000.0)


# ---- 输入引擎 -----------------------------------------------------------------
class MacOSInputEngine:
    """Quartz CGEvent 生产级输入引擎。

    用法：
        engine = MacOSInputEngine()
        engine.click(500, 300)
        engine.type_text("hello world")
        engine.hotkey("cmd", "c")
    """

    def __init__(self, *, inter_action_delay_ms: int = 50) -> None:
        self.delay_ms = inter_action_delay_ms

    def _pause(self) -> None:
        time.sleep(self.delay_ms / 1000.0)

    # ---- 鼠标 ----
    def move_mouse(self, x: int, y: int) -> None:
        _post(_mouse_event(Quartz.kCGEventMouseMoved, x, y, 0))
        self._pause()

    def click(self, x: int, y: int, *,
              button: MouseBtn = MouseBtn.LEFT,
              clicks: int = 1) -> None:
        """移动到坐标并点击。"""
        self.move_mouse(x, y)
        _sleep_ms(30)

        types = {
            MouseBtn.LEFT: (
                Quartz.kCGEventLeftMouseDown,
                Quartz.kCGEventLeftMouseUp),
            MouseBtn.RIGHT: (
                Quartz.kCGEventRightMouseDown,
                Quartz.kCGEventRightMouseUp),
            MouseBtn.MIDDLE: (
                Quartz.kCGEventOtherMouseDown,
                Quartz.kCGEventOtherMouseUp),
        }
        down_t, up_t = types[button]

        for _ in range(clicks):
            _post(_mouse_event(down_t, x, y, button))
            _sleep_ms(15)
            _post(_mouse_event(up_t, x, y, button))
            _sleep_ms(50)

    def double_click(self, x: int, y: int) -> None:
        self.click(x, y, clicks=2)

    def right_click(self, x: int, y: int) -> None:
        self.click(x, y, button=MouseBtn.RIGHT)

    def drag(self, from_x: int, from_y: int,
             to_x: int, to_y: int, *, duration_ms: int = 300) -> None:
        """拖拽：按下 → 平滑移动 → 松开。"""
        self.move_mouse(from_x, from_y)
        _sleep_ms(50)
        _post(_mouse_event(Quartz.kCGEventLeftMouseDown, from_x, from_y, 0))

        steps = max(int(duration_ms / 16), 2)  # ~60fps
        for i in range(1, steps + 1):
            t = i / steps
            ix = int(from_x + (to_x - from_x) * t)
            iy = int(from_y + (to_y - from_y) * t)
            _post(_mouse_event(
                Quartz.kCGEventLeftMouseDragged, ix, iy, 0))
            _sleep_ms(duration_ms // steps)

        _post(_mouse_event(Quartz.kCGEventLeftMouseUp, to_x, to_y, 0))
        self._pause()

    def scroll(self, amount: int, *, x: int = 0, y: int = 0) -> None:
        """滚动（正=向上）。"""
        for _ in range(abs(amount)):
            delta = 10 if amount > 0 else -10
            ev = Quartz.CGEventCreateScrollWheelEvent(
                None, Quartz.kCGScrollEventUnitByLine, 1, delta)
            _post(ev)
            _sleep_ms(20)

    # ---- 键盘 ----
    def type_text(self, text: str) -> None:
        """Unicode 字符串输入（支持中文）。"""
        for ch in text:
            down = _unicode_event(ch, True)
            up = _unicode_event(ch, False)
            _post(down); _post(up)
            _sleep_ms(5)

    def press_key(self, keycode: int | str) -> None:
        """按单个键（虚拟键码或名称）。"""
        code = KeyCode[keycode].value if isinstance(keycode, str) else keycode
        down = _key_event(code, True)
        up = _key_event(code, False)
        _post(down); _sleep_ms(15); _post(up)

    def hotkey(self, *keys: str) -> None:
        """组合键：hotkey("cmd", "shift", "s") 或 ("cmd", KeyCode.C)。"""
        modifiers = []
        normal_keys: List[int] = []
        for k in keys:
            kl = str(k).lower()
            if kl in MOD_FLAGS:
                modifiers.append(MOD_FLAGS[kl])
            else:
                try:
                    normal_keys.append(KeyCode[kl.upper()].value)
                except KeyError:
                    try:
                        normal_keys.append(int(k))
                    except ValueError:
                        pass

        # 按下所有修饰键
        mod_flag = sum(modifiers) if modifiers else 0
        for m in modifiers:
            ev = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
            Quartz.CGEventSetFlags(ev, m)
            _post(ev)

        # 按下并释放普通键
        for kc in normal_keys:
            ev_down = Quartz.CGEventCreateKeyboardEvent(None, kc, True)
            if modifiers:
                Quartz.CGEventSetFlags(ev_down, sum(modifiers))
            _post(ev_down)
            _sleep_ms(15)
            ev_up = Quartz.CGEventCreateKeyboardEvent(None, kc, False)
            if modifiers:
                Quartz.CGEventSetFlags(ev_up, sum(modifiers))
            _post(ev_up)

        # 释放修饰键
        for m in reversed(modifiers):
            ev = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
            Quartz.CGEventSetFlags(ev, m)
            _post(ev)

    def type_with_hotkey(self, text: str, *, pre_hotkey: Tuple[str] = ()) -> None:
        """先按组合键再输入文本（如 cmd+v 粘贴后打字）。"""
        if pre_hotkey:
            self.hotkey(*pre_hotkey)
            _sleep_ms(100)
        self.type_text(text)

    # ---- 屏幕感知 ----
    @staticmethod
    def screen_size() -> tuple:
        b = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        return int(b.size.width), int(b.size.height)

    @staticmethod
    def mouse_position() -> Tuple[float, float]:
        pos = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return (pos.x, pos.y)


# ---- 窗口管理 -----------------------------------------------------------------
class MacOSWindowManager:
    """基于 Quartz CGWindowList + NSWorkspace 的窗口管理。"""

    @staticmethod
    def list_windows() -> List[WindowInfo]:
        wl = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly |
            Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID)
        windows: List[WindowInfo] = []
        for w in wl:
            bounds = w.get("kCGWindowBounds", {})
            windows.append(WindowInfo(
                owner_name=w.get("kCGWindowOwnerName", "?"),
                window_name=w.get("kCGWindowName", ""),
                pid=w.get("kCGWindowPID", 0),
                layer=w.get("kCGWindowLayer", 0),
                bounds={k: v for k, v in bounds.items()},
            ))
        return windows


# ---- 快捷工厂 -----------------------------------------------------------------
_engine: Optional[MacOSInputEngine] = None


def get_input_engine() -> MacOSInputEngine:
    global _engine
    if _engine is None:
        _engine = MacOSInputEngine()
    return _engine