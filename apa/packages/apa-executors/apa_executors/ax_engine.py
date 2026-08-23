"""macOS Accessibility 元素识别引擎（影刀级 OS 底座 · M1）。

能力：
  - hit_test(x, y)          全系统命中测试：屏幕坐标 → AX 元素描述符
  - locate(desc)            按 ax_path 层级链重定位元素（跨启动稳定）
  - read_tree(root, depth)  限深子树遍历
  - press(desc)             双路径点击：AXPress 优先，降级坐标单击
  - wait_for(desc)          轮询重定位
  - 权限检测                辅助功能 / 屏幕录制

元素描述符（dict）：
  {app_name, pid, role, title, value, help, bounds{x,y,w,h},
   ax_path: [[role, same_role_index], ...]   # 根→目标，重定位依据
  }

坐标约定：全局点坐标，主屏左上角为原点（与 CGEvent 一致）。
pyobjc 约定：Copy* 返回 (err, value) 元组；AXValueGetValue 直接返回结构体。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import ApplicationServices as AS
except ImportError:  # 非 darwin 或未装框架
    AS = None  # type: ignore

try:
    import Quartz
except ImportError:  # pragma: no cover
    Quartz = None  # type: ignore


# ---------------------------------------------------------------------------
# 权限检测
# ---------------------------------------------------------------------------

def ax_trusted() -> bool:
    """辅助功能权限（EventTap/AX 读操作均需要）。"""
    if AS is None:
        return False
    return bool(AS.AXIsProcessTrusted())


def screen_capture_allowed() -> bool:
    """屏幕录制权限（截图/OCR 需要）。"""
    if Quartz is None:
        return False
    pre = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
    return bool(pre()) if pre else True


PERMISSION_HINTS = {
    "accessibility": (
        "系统设置 → 隐私与安全性 → 辅助功能 → 勾选终端/IDE/APA"),
    "screen_capture": (
        "系统设置 → 隐私与安全性 → 屏幕录制 → 勾选终端/IDE/APA"),
}


def _require() -> None:
    if AS is None:
        raise RuntimeError(
            "ApplicationServices unavailable: "
            "uv pip install pyobjc-framework-ApplicationServices")


# ---------------------------------------------------------------------------
# 属性读取工具
# ---------------------------------------------------------------------------

_ROLE = "AXRole"
_TITLE = "AXTitle"
_VALUE = "AXValue"
_HELP = "AXHelp"
_POSITION = "AXPosition"
_SIZE = "AXSize"
_CHILDREN = "AXChildren"
_PARENT = "AXParent"
_PRESS = "AXPress"


def _attr(el, name: str) -> Any:
    """读 AX 属性；失败返回 None。"""
    try:
        err, val = AS.AXUIElementCopyAttributeValue(el, name, None)
    except Exception:
        return None
    if err != 0:
        return None
    return val


def _pt_size(el) -> Tuple[Optional[Dict[str, float]],
                          Optional[Dict[str, float]]]:
    """读 AXPosition/AXSize → {'x','y'} / {'w','h'}。"""
    pos_v = _attr(el, _POSITION)
    size_v = _attr(el, _SIZE)
    pos = size = None
    if pos_v is not None:
        ok, p = AS.AXValueGetValue(pos_v, AS.kAXValueCGPointType, None)
        if ok and p is not None:  # pyobjc 返回 (成功?, CGPoint(x, y))
            pos = {"x": round(p.x, 1), "y": round(p.y, 1)}
    if size_v is not None:
        ok, s = AS.AXValueGetValue(size_v, AS.kAXValueCGSizeType, None)
        if ok and s is not None:
            size = {"w": round(s.width, 1), "h": round(s.height, 1)}
    return pos, size


# ---------------------------------------------------------------------------
# 描述符构造与重定位
# ---------------------------------------------------------------------------

def describe(el, *, include_value: bool = True,
             max_len: int = 120) -> Dict[str, Any]:
    """AX 元素 → 描述符 dict（含 ax_path 层级链）。"""
    err, pid = AS.AXUIElementGetPid(el, None)
    role = _plain(_attr(el, _ROLE))
    title = _plain(_attr(el, _TITLE)) or ""
    value = _plain(_attr(el, _VALUE)) if include_value else None
    help_ = _plain(_attr(el, _HELP)) or ""
    pos, size = _pt_size(el)
    bounds = None
    if pos and size:
        bounds = {"x": pos["x"], "y": pos["y"],
                  "w": size["w"], "h": size["h"]}
    return {
        "pid": int(pid) if err == 0 and pid is not None else -1,
        "app_name": _app_name(int(pid) if err == 0 and pid else -1),
        "role": role or "",
        "title": title[:max_len],
        "value": (str(value)[:max_len] if value is not None else None),
        "help": help_[:max_len],
        "bounds": bounds,
        "ax_path": build_ax_path(el),
    }


def _plain(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


def _app_name(pid: int) -> str:
    if pid < 0 or Quartz is None:
        return "?"
    try:
        wl = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly,
            Quartz.kCGNullWindowID) or []
        for w in wl:
            if w.get("kCGWindowPID") == pid:
                return w.get("kCGWindowOwnerName", "?")
    except Exception:
        pass
    return "?"


def systemwide():
    _require()
    return AS.AXUIElementCreateSystemWide()


def hit_test(x: float, y: float) -> Dict[str, Any]:
    """屏幕坐标 → 元素描述符。失败抛 RuntimeError。"""
    _require()
    sw = systemwide()
    err, el = AS.AXUIElementCopyElementAtPosition(sw, x, y, None)
    if err != 0 or el is None:
        raise RuntimeError(f"hit_test failed at ({x},{y}): err={err}")
    d = describe(el)
    d["_el"] = el  # 供同进程立即操作；序列化/跨进程时丢弃
    return d


def build_ax_path(el) -> List[List[Any]]:
    """自底向上爬 parent 链。条目 = [role, 同角色序号, title|None]。

    title 作为失配恢复的锚点（动态 WebArea 的纯序号路径不可靠）。
    """
    chain: List[List[Any]] = []
    cur = el
    seen = 0
    while cur is not None and seen < 64:
        seen += 1
        role = _plain(_attr(cur, _ROLE)) or ""
        title = (_plain(_attr(cur, _TITLE)) or "")[:80]
        parent = _attr(cur, _PARENT)
        if parent is None:
            break
        idx = _same_role_index(parent, cur, role)
        chain.append([role, idx, title or None])
        cur = parent
    chain.reverse()
    return chain


def _same_role_index(parent, child, role: str) -> int:
    kids = _attr(parent, _CHILDREN) or []
    n = 0
    for k in kids:
        if (_plain(_attr(k, _ROLE)) or "") == role:
            if _el_equal(k, child):
                return n
            n += 1
    return 0


def _el_equal(a, b) -> bool:
    try:
        from CoreFoundation import CFEqual

        return bool(CFEqual(a, b))
    except Exception:
        return a is b


def _resolve_root(pid: int):
    if pid and pid > 0:
        app = AS.AXUIElementCreateApplication(pid)
        if app is not None and _attr(app, _ROLE) is not None:
            return app
    return systemwide()


def locate(desc: Dict[str, Any], *, retries: int = 2) -> Optional[Any]:
    """按描述符 ax_path 重定位 AX 元素。找不到返回 None。

    策略（影刀同款三级）：
      1. 严格路径：pid 定根 → 同角色序号逐层下钻
      2. 锚点恢复：某层失配时，从最近有效节点出发按
         (role, title) 在有限子树内搜索剩余路径的末端锚点
      3. 树未稳定时整体重试（动态 WebArea 快照漂移）
    """
    _require()
    for attempt in range(max(1, retries + 1)):
        el = _locate_once(desc)
        if el is not None:
            return el
        if attempt < retries:
            time.sleep(0.25)
    return None


def _locate_once(desc: Dict[str, Any]) -> Optional[Any]:
    path = desc.get("ax_path") or []
    if not path:
        return None
    cur = _resolve_root(int(desc.get("pid") or 0))
    last_good = cur

    for i, step in enumerate(path):
        role = str(step[0])
        idx = int(step[1]) if len(step) > 1 else 0
        title = step[2] if len(step) > 2 else None

        kids = _attr(cur, _CHILDREN) or []
        same = [k for k in kids
                if (_plain(_attr(k, _ROLE)) or "") == role]
        nxt = same[idx] if idx < len(same) else None

        if nxt is not None:
            last_good = nxt
            cur = nxt
            continue

        # ---- 失配恢复（三级）----
        # ① 标题锚点：浅层后代找 role+title 匹配
        if title:
            nxt = _find_by_anchor(cur, role, title, max_depth=6)
            if nxt is not None:
                last_good = nxt
                cur = nxt
                continue
        # ② 几何包含：原 bounds 中心 → 最小面积包含节点
        want_bounds = desc.get("bounds")
        if want_bounds:
            cx = want_bounds["x"] + want_bounds["w"] / 2
            cy = want_bounds["y"] + want_bounds["h"] / 2
            nxt = _find_by_geometry(last_good, cx, cy,
                                    want_role=role, max_depth=7)
            if nxt is not None:
                last_good = nxt
                cur = nxt
                continue
        return None

    got = _plain(_attr(cur, _ROLE)) or ""
    want = str(path[-1][0])
    return cur if got == want else None


def _find_by_anchor(root, role: str, title: str,
                    *, max_depth: int = 6) -> Optional[Any]:
    """DFS 找 (role 相符 && title 相符) 的第一个节点。"""

    def walk(el, depth: int) -> Optional[Any]:
        if depth > max_depth:
            return None
        r = _plain(_attr(el, _ROLE)) or ""
        t = _plain(_attr(el, _TITLE)) or ""
        if r == role and t == title:
            return el
        for k in (_attr(el, _CHILDREN) or []):
            hit = walk(k, depth + 1)
            if hit is not None:
                return hit
        return None

    return walk(root, 0)


def _find_by_geometry(root, cx: float, cy: float, *,
                      want_role: str = "", max_depth: int = 7):
    """DFS 找 bounds 包含点 (cx,cy) 的最小面积节点。

    优先返回 role 相符者；无 role 匹配时回退最小包含节点
    （动态 UI 角色换名但布局稳定的场景）。
    """
    best_strict = None
    best_loose = None
    best_area = float("inf")

    def area(b) -> float:
        return max(0.0, b["w"]) * max(0.0, b["h"])

    def walk(el, depth: int) -> None:
        nonlocal best_strict, best_loose, best_area
        if depth > max_depth:
            return
        b = _pt_size(el)
        pos, size = b
        if pos and size:
            x0, y0 = pos["x"], pos["y"]
            x1, y1 = x0 + size["w"], y0 + size["h"]
            if x0 - 1 <= cx <= x1 + 1 and y0 - 1 <= cy <= y1 + 1:
                a = area(size)
                r = _plain(_attr(el, _ROLE)) or ""
                if a < best_area:
                    best_area = a
                    best_loose = el
                    if r == want_role:
                        best_strict = el
        for k in (_attr(el, _CHILDREN) or []):
            walk(k, depth + 1)

    walk(root, 0)
    return best_strict if best_strict is not None else best_loose


def read_tree(root=None, *, max_depth: int = 4,
              max_nodes: int = 300) -> List[Dict[str, Any]]:
    """限深遍历子树 → 描述符列表。root 缺省用 systemwide。"""
    _require()
    out: List[Dict[str, Any]] = []

    def walk(el, depth: int) -> None:
        if len(out) >= max_nodes or depth > max_depth:
            return
        d = describe(el, include_value=False)
        out.append(d)
        for k in (_attr(el, _CHILDREN) or []):
            walk(k, depth + 1)
            if len(out) >= max_nodes:
                return

    start = root if root is not None else systemwide()
    walk(start, 0)
    return out


# ---------------------------------------------------------------------------
# 双路径操作
# ---------------------------------------------------------------------------

def can_press(el) -> bool:
    err, names = AS.AXUIElementCopyActionNames(el, None)
    if err != 0 or not names:
        return False
    return _PRESS in [str(a) for a in names]


def press(desc: Dict[str, Any], *, fallback_click=None) -> Dict[str, Any]:
    """双路径点击：AXPress 可用即执行；否则 fallback_click(cx, cy) 坐标兜底。

    返回 {path_used: 'ax'|'coord', element: 描述符(无 _el)}。
    """
    _require()
    el = desc.get("_el") or locate(desc)
    if el is None:
        raise RuntimeError("element not relocatable")
    d = describe(el)
    d.pop("_el", None)

    if can_press(el):
        err = AS.AXUIElementPerformAction(el, _PRESS)
        if err == 0:
            return {"path_used": "ax", "element": d}

    b = d.get("bounds")
    if not b:
        raise RuntimeError("no AXPress and no bounds for coord fallback")
    if fallback_click is None:
        raise RuntimeError("AXPress failed and no fallback provided")
    cx = int(b["x"] + b["w"] / 2)
    cy = int(b["y"] + b["h"] / 2)
    fallback_click(cx, cy)
    d["clicked_at"] = [cx, cy]
    return {"path_used": "coord", "element": d}


def wait_for(desc: Dict[str, Any], *,
             timeout_s: float = 10.0,
             interval_s: float = 0.4) -> Optional[Dict[str, Any]]:
    """轮询重定位直到出现或超时。返回新描述符或 None。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        el = locate(desc)
        if el is not None:
            return describe(el)
        time.sleep(interval_s)
    return None