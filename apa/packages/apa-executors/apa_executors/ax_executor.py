"""apa-executors: macOS AX 元素操作执行器（影刀级 OS 底座 · M1）。

动作域：desktop.ui.* / desktop.click_text
  desktop.ui.read_element   命中测试或按描述符重定位 → 元素描述符
  desktop.ui.read_tree      从坐标/应用根限深遍历元素树
  desktop.ui.click_element  双路径点击（AXPress 优先，坐标兜底）
  desktop.ui.wait_element   轮询等待描述符对应元素出现
  desktop.click_text        Vision OCR 定位屏幕文字 → 坐标点击

权限：辅助功能（AX/EventTap）+ 屏幕录制（OCR 截屏）。
非 darwin 或缺框架时动作返回 dependency_missing，不阻塞进程其余部分。
"""
from __future__ import annotations

from typing import Tuple

try:
    from . import ax_engine as ax
except ImportError:  # pragma: no cover
    ax = None  # type: ignore

try:
    from .macos_engine import InputEngine
except ImportError:  # pragma: no cover
    InputEngine = None  # type: ignore

from apa_sdk.executor_base import AIPExecutor


class AXExecutor(AIPExecutor):
    """AX 元素识别与操作。"""

    def __init__(self, source: str, session_id: str, transport=None, *,
                 context_store=None) -> None:
        super().__init__(source, session_id, transport,
                         context_store=context_store)
        self._input = InputEngine() if InputEngine else None

    def start_observation(self) -> None:
        pass

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        # Phase A：模拟真人开关（作用于本执行器的 InputEngine）
        if name == "desktop.humanize":
            if self._input is None:
                return False, {"code": "dependency_missing",
                               "detail": "InputEngine unavailable"}
            self._input.humanize = bool(params.get("enabled", True))
            return True, {"humanize": self._input.humanize}

        if ax is None:
            return False, {"code": "dependency_missing",
                           "detail": "requires darwin + pyobjc "
                                     "ApplicationServices"}
        try:
            handler = {
                "desktop.ui.read_element": self._read_element,
                "desktop.ui.read_tree": self._read_tree,
                "desktop.ui.click_element": self._click_element,
                "desktop.ui.wait_element": self._wait_element,
                "desktop.click_text": self._click_text,
            }.get(name)
            if handler is None:
                return False, {"code": "action_not_supported_by_executor"}
            return handler(params)
        except PermissionError as e:
            return False, {"code": "permission_denied",
                           "detail": str(e),
                           "hint": ax.PERMISSION_HINTS["accessibility"]}
        except RuntimeError as e:
            msg = str(e)
            code = ("not_trusted" if "trusted" in msg.lower()
                    else "ax_error")
            return False, {"code": code, "detail": msg}
        except Exception as e:  # noqa: BLE001
            return False, {"code": type(e).__name__, "detail": str(e)}

    # ---- 权限前置 -----------------------------------------------------------

    def _check_ax(self):
        if not ax.ax_trusted():
            raise RuntimeError(
                f"accessibility not trusted — {ax.PERMISSION_HINTS['accessibility']}")

    # ---- 动作实现 -----------------------------------------------------------

    def _read_element(self, p: dict) -> Tuple[bool, dict]:
        self._check_ax()
        desc = p.get("element")
        if desc and (desc.get("ax_path")):
            el = ax.locate(desc)
            if el is None:
                return False, {"code": "element_not_found"}
            d = ax.describe(el)
        elif desc and "x" in desc and "y" in desc and not desc.get("bounds"):
            d = ax.hit_test(float(desc["x"]), float(desc["y"]))
        else:
            x = float(p.get("x", -1))
            y = float(p.get("y", -1))
            d = ax.hit_test(x, y)
        d.pop("_el", None)
        out = {"element": d}
        self._store(out, p.get("output_context"))
        return True, out

    def _read_tree(self, p: dict) -> Tuple[bool, dict]:
        self._check_ax()
        root = None
        pid = p.get("pid")
        if pid:
            import ApplicationServices as AS
            root = AS.AXUIElementCreateApplication(int(pid))
        nodes = ax.read_tree(root,
                             max_depth=int(p.get("max_depth", 4)),
                             max_nodes=int(p.get("max_nodes", 200)))
        out = {"nodes": nodes, "count": len(nodes)}
        self._store(out, p.get("output_context"))
        return True, out

    def _click_element(self, p: dict) -> Tuple[bool, dict]:
        self._check_ax()
        desc = p.get("element") or {}
        fallback = None
        if self._input is not None:
            fallback = lambda cx, cy: self._input.click(cx, cy)  # noqa: E731
        r = ax.press(desc, fallback_click=fallback)
        out = {"path_used": r["path_used"], **r["element"]}
        self._store(out, p.get("output_context"))
        return True, out

    def _wait_element(self, p: dict) -> Tuple[bool, dict]:
        self._check_ax()
        found = ax.wait_for(p.get("element") or {},
                            timeout_s=float(p.get("timeout_s", 10.0)),
                            interval_s=float(p.get("interval_s", 0.4)))
        if found is None:
            return False, {"code": "element_timeout"}
        out = {"element": found}
        self._store(out, p.get("output_context"))
        return True, out

    def _click_text(self, p: dict) -> Tuple[bool, dict]:
        from . import screen_ocr as so

        target = str(p.get("text", ""))
        if not target:
            return False, {"code": "missing_param", "detail": "text"}
        region = p.get("region")
        offset = region or {}
        hit = so.locate_text(target, region=region,
                             contains=p.get("contains", True),
                             min_confidence=float(
                                 p.get("min_confidence", 0.3)))
        if hit is None:
            return False, {"code": "text_not_found", "text": target}

        b = hit["bounds"]
        # 区域模式：局部坐标 → 全局点坐标
        gx = b["x"] + b["w"] / 2 + float(offset.get("x", 0))
        gy = b["y"] + b["h"] / 2 + float(offset.get("y", 0))
        if self._input is None:
            return False, {"code": "dependency_missing",
                           "detail": "InputEngine unavailable"}
        self._input.click(int(gx), int(gy))
        out = {"clicked_at": [int(gx), int(gy)],
               "matched_text": hit["text"],
               "confidence": hit["confidence"]}
        self._store(out, p.get("output_context"))
        return True, out

    def _store(self, data: dict, key) -> None:
        if key and self.context_store is not None:
            ref = self.context_store.make_ref(self.peer.session_id, str(key))
            self.context_store.put(ref, data)