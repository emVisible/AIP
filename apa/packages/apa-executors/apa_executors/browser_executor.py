"""apa-executors: BrowserExecutor（设计文档 §5.3）。

基于 Playwright 的 Web 自动化执行器。感知策略：DOM 解析 → VLM fallback（C6）。
VLM 在 Executor 内部使用，产物是语义元素列表，不进入 AIP 协议。

设计：
  · 通过 PageOps 抽象解耦 Playwright 与 MockPage（可测试）
  · 动作：navigate/click/input/extract/select_option/wait_element/scroll/
         take_screenshot + 基类内置 context.*
  · 目标解析优先级：data-apa-id → aria-label/role+text → CSS（§5.3）
  · 每次状态变化后执行语义提升（SemanticAdapter），把上下文引用而非原始 DOM
    发给 Decision Engine（C5/C6）
"""
from __future__ import annotations

import base64
from typing import Dict, List, Optional, Tuple

from apa_sdk import AIPExecutor, ExecutorPreconditionError, SemanticAdapter
from apa_sdk.semantic_adapter import Element, ScreenState

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


class PageOps:
    """浏览器操作抽象。PlaywrightPageOps 与 MockPage 都实现此接口。"""

    url: str = ""
    title: str = ""
    loads: int = 0

    def goto(self, url: str, wait_until: str = "networkidle") -> None:
        raise NotImplementedError

    def resolve(self, target: str):
        """按优先级返回可操作对象：data-apa-id → label/role+text → CSS。"""
        raise NotImplementedError

    def click(self, target: str, force: bool = False) -> None:
        raise NotImplementedError

    def fill(self, target: str, value: str, clear_first: bool = True) -> None:
        raise NotImplementedError

    def inner_text(self, target: str) -> str:
        raise NotImplementedError

    def select_option(self, target: str, value: str) -> None:
        raise NotImplementedError

    def wait_for(self, target: str, timeout_ms: int = 30000) -> None:
        raise NotImplementedError

    def scroll(self, direction: str) -> None:
        raise NotImplementedError

    def screenshot_bytes(self) -> bytes:
        raise NotImplementedError

    def all_elements(self) -> List[Element]:
        """当前页面的可访问元素模型（供语义适配器）。"""
        raise NotImplementedError

    def wait_for_load_state(self, state: str = "networkidle") -> None:
        raise NotImplementedError


class PlaywrightPageOps(PageOps):
    def __init__(self, page) -> None:
        self.page = page

    @property
    def url(self) -> str:
        return self.page.url

    @property
    def title(self) -> str:
        return self.page.title()

    @property
    def loads(self) -> int:
        return self.page.evaluate("window.performance.navigation.type")

    def goto(self, url: str, wait_until: str = "networkidle") -> None:
        self.page.goto(url, wait_until=wait_until)

    def _locator(self, target: str):
        if target.startswith(("#", ".", "[", "//")):
            return self.page.locator(target)  # 已是 CSS/XPath 选择器，直接用
        loc = self.page.locator(f"[data-apa-id='{target}']")
        try:
            if loc.count() == 0:
                loc = self.page.get_by_label(target)
            if loc.count() == 0:
                loc = self.page.get_by_role("button", name=target)
        except Exception:
            pass
        return loc

    def resolve(self, target: str):
        return self._locator(target)

    def click(self, target: str, force: bool = False) -> None:
        self._locator(target).click(force=force)

    def fill(self, target: str, value: str, clear_first: bool = True) -> None:
        loc = self._locator(target)
        if clear_first:
            loc.clear()
        loc.fill(value)

    def inner_text(self, target: str) -> str:
        return self._locator(target).inner_text()

    def select_option(self, target: str, value: str) -> None:
        self._locator(target).select_option(value)

    def wait_for(self, target: str, timeout_ms: int = 30000) -> None:
        self._locator(target).first.wait_for(timeout=timeout_ms)

    def scroll(self, direction: str) -> None:
        delta = {"up": -400, "down": 400, "to_top": 0, "to_bottom": 10 ** 9}
        if direction in ("to_top", "to_bottom"):
            self.page.evaluate("(delta) => window.scrollTo(0, delta)",
                               direction)
        else:
            self.page.mouse.wheel(0, delta[direction])

    def screenshot_bytes(self) -> bytes:
        return self.page.screenshot()

    def all_elements(self) -> List[Element]:
        els: List[Element] = []
        # 常见标签 → 隐式 ARIA role（供语义适配器按角色匹配）
        implicit_roles = {
            "h1": "heading", "h2": "heading", "h3": "heading",
            "h4": "heading", "h5": "heading", "h6": "heading",
            "button": "button", "a": "link",
            "input": "textbox", "textarea": "textbox",
            "select": "combobox", "tr": "row", "td": "cell", "th": "cell",
            "table": "table", "form": "form", "dialog": "dialog",
            "label": "label", "option": "option", "img": "img",
        }
        for loc in self.page.locator("[data-apa-id]").all():
            try:
                data_id = loc.get_attribute("data-apa-id") or ""
            except Exception:
                data_id = ""
            try:
                tag_role = loc.evaluate(
                    "el => el.getAttribute('role') || el.tagName.toLowerCase()")
            except Exception:
                tag_role = ""
            role = implicit_roles.get(tag_role, tag_role)
            try:
                text = loc.inner_text()
            except Exception:
                text = ""
            try:
                aria = loc.get_attribute("aria-label") or ""
            except Exception:
                aria = ""
            try:
                el_id = loc.get_attribute("id") or ""
            except Exception:
                el_id = ""
            attrs = {}
            try:
                attrs = loc.evaluate("el => { const o={}; for (const a of el.attributes) o[a.name]=a.value; return o }")
            except Exception:
                pass
            els.append(Element(role=role, text=text, id=el_id,
                               data_apa_id=data_id, aria_label=aria, attrs=attrs))
        return els

    def wait_for_load_state(self, state: str = "networkidle") -> None:
        self.page.wait_for_load_state(state)


class BrowserExecutor(AIPExecutor):
    def __init__(
        self,
        source: str,
        session_id: str,
        transport=None,
        *,
        page: Optional[PageOps] = None,
        adapter: Optional[SemanticAdapter] = None,
        context_store=None,
        vision=None,
        recorder=None,
    ) -> None:
        super().__init__(source, session_id, transport, context_store=context_store)
        self.page = page
        self.adapter = adapter or SemanticAdapter()
        self.vision = vision  # VisionAdapter：DOM 感知失败时的本地降级（C6）
        self.recorder = recorder  # SchemaRecorder：录制模式（§B.1）
        self._observe_counter = 0
        self._last_signature: Optional[str] = None
        self.vision_fallbacks = 0

    def _record(self, name: str, params: dict) -> None:
        if self.recorder is None:
            return
        try:
            state = (self.page.screen_state() if hasattr(self.page, "screen_state")
                     else ScreenState(url=self.page.url, title=self.page.title,
                                      elements=self.page.all_elements()))
            self.recorder.record_action(name, params, state)
        except Exception:
            pass  # 录制失败不影响执行

    # --- 观察循环 -------------------------------------------------------------
    def start_observation(self) -> None:
        """由 driver 调用。POC：观察动作副作用，不做后台轮询。"""

    def _observe(self) -> None:
        """捕获当前页面状态 → 语义提升 → 发事件（只传引用，C5/C6）。

        感知降级链（§5.3/§5.4）：DOM 解析 → VLM 本地分析（C6：
        截图与坐标不进入协议）。状态未变化时跳过（防事件风暴）。
        """
        if hasattr(self.page, "screen_state"):
            state = self.page.screen_state()
            # MockPage：元素为空且启用视觉 → 本地降级
            if not state.elements and self.vision is not None:
                state = self._vision_fallback(state)
        else:
            elements = self.page.all_elements()
            if not elements and self.vision is not None:
                elements = self.vision.understand_screen(
                    self.page.screenshot_bytes())
                self.vision_fallbacks += 1
                for e in elements:
                    e.bounds = None  # C6：坐标剥离于入协议前
            state = ScreenState(url=self.page.url, title=self.page.title,
                                elements=elements)
        signature = _state_signature(state)
        if signature == self._last_signature:
            return  # 页面无变化，不重复发事件
        self._last_signature = signature
        for ev in self.adapter.lift(state):
            self._observe_counter += 1
            # 语义适配器已把物理元素翻译为业务字段（含 transform），
            # 存入 ContextStore 供决策引擎按需 fetch（CoD-3）
            ref = self.context_store.make_ref(self.peer.session_id, f"page_{self._observe_counter}")
            self.context_store.put(ref, {
                "url": state.url, "title": state.title, **ev.data})
            data = dict(ev.data)
            data["context"] = ref
            self.emit(ev.name, data)

    def _vision_fallback(self, state: ScreenState) -> ScreenState:
        """MockPage 路径的视觉降级：截图 → 本地 VLM → 语义元素（C6）。"""
        try:
            elements = self.vision.understand_screen(b"mock-screenshot")
            self.vision_fallbacks += 1
            for e in elements:
                e.bounds = None
            return ScreenState(url=state.url, title=state.title,
                               elements=elements)
        except Exception:
            return state

    # --- 动作执行 -------------------------------------------------------------
    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        if self.page is None:
            return False, {"code": "browser_not_ready"}
        match name:
            case "browser.navigate":
                self.page.goto(params["url"], params.get("wait_for", "networkidle"))
                self._record(name, params)
                self._observe()
                return True, {"url": params["url"]}

            case "browser.click":
                self.page.click(params["target"], force=params.get("force", False))
                self._record(name, params)
                self._observe()
                return True, {"target": params["target"]}

            case "browser.input":
                self.page.fill(params["target"], params["value"],
                               clear_first=params.get("clear_first", True))
                self._record(name, params)
                self._observe()
                return True, {"target": params["target"]}

            case "browser.select_option":
                self.page.select_option(params["target"], params["value"])
                self._observe()
                return True, {"target": params["target"]}

            case "browser.extract":
                result: Dict[str, str] = {}
                for field, selector in params["selectors"].items():
                    try:
                        result[field] = self.page.inner_text(selector)
                    except Exception:
                        result[field] = ""
                ref = params.get("output_context",
                                 self.context_store.make_ref(self.peer.session_id, "extract"))
                self.context_store.put(ref, result)
                return True, {"output_context": ref}

            case "browser.wait_element":
                self.page.wait_for(params["target"], params.get("timeout_ms", 30000))
                return True, {"target": params["target"]}

            case "browser.scroll":
                self.page.scroll(params["direction"])
                return True, {"direction": params["direction"]}

            case "browser.take_screenshot":
                data = self.page.screenshot_bytes()
                ref = params.get("output_context",
                                 self.context_store.make_ref(self.peer.session_id, "screenshot"))
                self.context_store.put(ref, {
                    "bytes": len(data),
                    "b64_prefix": base64.b64encode(data[:16]).decode(),
                    "mime": "image/png",
                })
                return True, {"output_context": ref, "size_bytes": len(data)}

            case _:
                return False, {"code": "action_not_supported_by_executor"}

    # --- 便捷 -----------------------------------------------------------------
    def navigate(self, url: str, wait_for: str = "networkidle") -> None:
        self.page.goto(url, wait_for)

    def trigger_navigate(self, url: str) -> None:
        """对外触发导航（demo 用）：导航 + 观察 + 发出语义事件。"""
        self.page.goto(url, "networkidle")
        self._observe()


def _elements_to_dict(elements: List[Element]) -> List[dict]:
    return [
        {"role": e.role, "text": e.text, "id": e.id,
         "data_apa_id": e.data_apa_id, "aria_label": e.aria_label}
        for e in elements
    ]


def _state_signature(state: ScreenState) -> str:
    """页面状态签名：url + title + 元素摘要。用于变化检测。"""
    parts = [state.url, state.title]
    for e in state.elements:
        parts.append(f"{e.role}|{e.text}|{e.data_apa_id}|{sorted(e.attrs.items())}")
    return "|".join(parts)


def open_browser(headless: bool = True) -> tuple:
    """启动 Playwright 并返回 (playwright, browser, page, PageOps)。"""
    if sync_playwright is None:
        raise RuntimeError("playwright is required: pip install playwright")
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless)
    page = browser.new_page()
    return pw, browser, page, PlaywrightPageOps(page)