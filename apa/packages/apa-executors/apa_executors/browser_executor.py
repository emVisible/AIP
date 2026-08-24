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
import os
from pathlib import Path
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

    def extract_table(self, row_selector: str,
                      columns: Dict[str, str],
                      max_rows: int = 100) -> List[Dict[str, str]]:
        raise NotImplementedError

    # A1/A2：frame 与登录态（默认不支持的后端抛 NotImplementedError）
    def set_frame(self, index: Optional[int] = None,
                  selector: Optional[str] = None) -> None:
        raise NotImplementedError

    def reset_frame(self) -> None:
        raise NotImplementedError

    def storage_state_save(self, path: str) -> None:
        raise NotImplementedError

    def storage_state_load(self, path: str) -> None:
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
        # A1: 当前 frame 上下文（None = 主文档）。
        # 定位统一经 _locator() 穿透；set_frame 可嵌套，reset 回主文档。
        self._fl = None

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

    def _root(self):
        """定位根：frame 上下文存在时返回 FrameLocator，否则 Page。"""
        return self._fl if self._fl is not None else self.page

    def _locator(self, target: str):
        root = self._root()
        if target.startswith(("#", ".", "[", "//")):
            return root.locator(target)  # 已是 CSS/XPath 选择器，直接用
        loc = root.locator(f"[data-apa-id='{target}']")
        try:
            if loc.count() == 0:
                loc = root.get_by_label(target)
            if loc.count() == 0:
                loc = root.get_by_role("button", name=target)
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

    def extract_table(self, row_selector: str,
                      columns: Dict[str, str],
                      max_rows: int = 100) -> List[Dict[str, str]]:
        """结构化表格抓取：按行选择器 + 每列子选择器提取。"""
        rows_out: List[Dict[str, str]] = []
        row_locs = self.page.locator(row_selector)
        count = min(row_locs.count(), max_rows)
        for i in range(count):
            row: Dict[str, str] = {}
            for field, col_sel in columns.items():
                try:
                    row[field] = row_locs.nth(i).locator(col_sel) \
                        .first.inner_text().strip()
                except Exception:
                    row[field] = ""
            rows_out.append(row)
        return rows_out

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
    # ---- A1/A2: frame 与登录态 ----------------------------------------------

    def set_frame(self, selector: Optional[str] = None,
                  index: Optional[int] = None) -> None:
        """进入子 frame（selector 优先）。可嵌套调用；reset_frame 返回。"""
        if selector:
            parent = self._fl if self._fl is not None else self.page
            self._fl = parent.frame_locator(selector)
            return
        idx = int(index or 0)
        frames = self.page.frames
        if idx >= len(frames):
            raise IndexError(f"frame index {idx} out of range "
                             f"(have {len(frames)})")
        fr = frames[idx]
        # 用 frame url/name 构造稳定选择器链
        sel = (f'iframe[name="{fr.name}"]' if fr.name
               else "iframe")
        parent_fl = self.page.frame_locator(sel)
        # 非首帧时按 index 取第 n 个匹配
        if idx > 0 and not fr.name:
            parent_fl = parent_fl.nth(idx)
        self._fl = parent_fl

    def reset_frame(self) -> None:
        self._fl = None

    def storage_state_save(self, path: str) -> None:
        import json as _j

        state = self.page.context.storage_state()
        Path(path).write_text(_j.dumps(state, ensure_ascii=False),
                              encoding="utf-8")

    def storage_state_load(self, path: str) -> None:
        from pathlib import Path as _P

        p = _P(path)
        if not p.is_file():
            raise FileNotFoundError(path)
        import json as _j

        state = _j.loads(p.read_text(encoding="utf-8"))
        cookies = state.get("cookies") or []
        if cookies:
            self.page.context.add_cookies(cookies)




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

            case "browser.extract_table":
                rows = self.page.extract_table(
                    params["row_selector"],
                    params["columns"],
                    params.get("max_rows", 100),
                )
                ref = params.get("output_context",
                                 self.context_store.make_ref(
                                     self.peer.session_id, "table"))
                self.context_store.put(ref, {"rows": rows,
                                             "count": len(rows)})
                self._record(name, params)
                return True, {"output_context": ref, "count": len(rows)}

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

            # ---- M3 浏览器高级 -------------------------------------------------
            case "browser.tab_new":
                return self._tab_new(params)
            case "browser.tab_list":
                return self._tab_list()
            case "browser.tab_switch":
                return self._tab_switch(params)
            case "browser.tab_close":
                return self._tab_close(params)

            case "browser.execute_js":
                script = params["script"]
                arg = params.get("arg")
                value = self.page.page.evaluate(script, arg)
                return True, {"value": _jsonable(value)}

            case "browser.upload":
                files = params.get("files") or []
                self.page.resolve(params["target"]).set_input_files(files)
                self._record(name, params)
                return True, {"target": params["target"],
                              "count": len(files)}

            case "browser.download":
                return self._download(params)

            case "browser.cookies_get":
                cookies = self.page.page.context.cookies(
                    params.get("urls"))
                return True, {"cookies": cookies, "count": len(cookies)}

            case "browser.cookies_set":
                items = params.get("cookies") or []
                self.page.page.context.add_cookies(items)
                return True, {"added": len(items)}

            case "browser.cookies_clear":
                self.page.page.context.clear_cookies()
                return True, {"cleared": True}

            case "browser.hover":
                self.page.resolve(params["target"]).hover()
                self._record(name, params)
                return True, {"target": params["target"]}

            case "browser.double_click":
                self.page.resolve(params["target"]).dblclick()
                self._record(name, params)
                return True, {"target": params["target"]}

            case "browser.right_click":
                self.page.resolve(params["target"]).click(button="right")
                self._record(name, params)
                return True, {"target": params["target"]}

            case "browser.get_page_info":
                return True, {"url": self.page.url,
                              "title": self.page.title}

            case "browser.iframe_switch":
                self.page.set_frame(selector=params.get("selector"),
                                    index=params.get("index"))
                return True, {"frame": params.get("selector")
                              or f"index:{params.get('index', 0)}"}

            case "browser.frame_reset":
                self.page.reset_frame()
                return True, {"frame": "main"}

            case "browser.get_similar_elements":
                sel = params["selector"]
                limit = int(params.get("limit", 100))
                locs = self.page.resolve(sel)
                count = min(locs.count(), limit)
                items = []
                for i in range(count):
                    el = locs.nth(i)
                    try:
                        text = el.inner_text().strip()[:120]
                    except Exception:
                        text = ""
                    try:
                        bb = el.bounding_box() or {}
                    except Exception:
                        bb = {}
                    items.append({"index": i, "text": text,
                                  "bounds": {k: round(v, 1)
                                              for k, v in bb.items()}
                                  if bb else None})
                ref = params.get("output_context")
                if ref and self.context_store is not None:
                    r = self.context_store.make_ref(self.peer.session_id,
                                                     str(ref))
                    self.context_store.put(r, {"elements": items,
                                                "count": len(items)})
                return True, {"elements": items, "count": len(items),
                              **({"output_context": ref} if ref else {})}

            case "browser.dialog_handle":
                # 注册一次性 dialog 处理器：下一个弹窗自动应答
                action = params.get("action", "accept")
                prompt_text = str(params.get("prompt_text", ""))

                def _on_dialog(dlg):
                    try:
                        if dlg.type == "prompt" and \
                                action == "accept":
                            dlg.accept(prompt_text)
                        elif action == "dismiss":
                            dlg.dismiss()
                        else:
                            dlg.accept()
                    finally:
                        self.page.page.remove_listener(
                            "dialog", _on_dialog)

                self.page.page.on("dialog", _on_dialog)
                return True, {"armed": action}

            case "browser.drag_drop":
                src = self.page.resolve(params["from"])
                dst = self.page.resolve(params["to"])
                src.drag_to(dst)
                self._record(name, params)
                return True, {"from": params["from"],
                              "to": params["to"]}

            case "browser.scroll_to_element":
                self.page.resolve(params["target"]) \
                    .scroll_into_view_if_needed()
                return True, {"target": params["target"]}

            case "browser.get_element_count":
                cnt = self.page.resolve(params["selector"]).count()
                return True, {"count": cnt}

            case "browser.wait_close":
                self.page.resolve(params["target"]).first \
                    .wait_for(state="detached",
                              timeout=params.get("timeout_ms", 10000))
                return True, {"target": params["target"]}

            case "if.element_visible":
                try:
                    visible = self.page.resolve(
                        params["target"]).is_visible()
                except Exception:
                    visible = False
                return True, {"matched": bool(visible)}

            case "if.url_contains":
                frag = str(params.get("fragment", ""))
                return True, {"matched": frag in (self.page.url or "")}

            case "browser.storage_state_save":
                path = params["path"]
                self.page.storage_state_save(path)
                return True, {"path": path}

            case "browser.storage_state_load":
                path = params["path"]
                self.page.storage_state_load(path)
                return True, {"path": path}

            case "browser.element_attr":
                attr = params["attr"]
                val = self.page.resolve(params["target"]) \
                    .get_attribute(attr, timeout=params.get("timeout_ms", 5000))
                return True, {"attr": attr, "value": val}

            case _:
                return False, {"code": "action_not_supported_by_executor"}

    # --- M3 tab / download 内部实现 ------------------------------------------

    def _tabs(self) -> Dict[str, PageOps]:
        """惰性注册表：首个调用把当前 page 登记为 tab_1。"""
        if not hasattr(self, "_tab_map"):
            self._tab_map: Dict[str, PageOps] = {}
        if not self._tab_map:
            self._tab_map["tab_1"] = self.page
            self._active_ref = "tab_1"
        return self._tab_map

    def _tab_new(self, params: dict) -> Tuple[bool, dict]:
        ctx = self.page.page.context
        raw = ctx.new_page()
        ref = params.get("ref") or f"tab_{len(self._tabs()) + 1}"
        ops = PlaywrightPageOps(raw)
        self._tabs()[ref] = ops
        url = params.get("url")
        if url:
            raw.goto(url, wait_until=params.get("wait_for", "networkidle"))
        self.page = ops
        self._active_ref = ref
        self._observe()
        return True, {"ref": ref, "url": self.page.url}

    def _tab_list(self) -> Tuple[bool, dict]:
        items = [{"ref": r, "url": o.url, "title": o.title}
                 for r, o in self._tabs().items()]
        active = getattr(self, "_active_ref", None)
        for it in items:
            it["active"] = it["ref"] == active
        return True, {"tabs": items, "count": len(items),
                      "active": active}

    def _tab_switch(self, params: dict) -> Tuple[bool, dict]:
        ref = params["ref"]
        tabs = self._tabs()
        if ref not in tabs:
            return False, {"code": "tab_not_found", "ref": ref}
        self.page = tabs[ref]
        self._active_ref = ref
        self._observe()
        return True, {"ref": ref, "url": self.page.url,
                      "title": self.page.title}

    def _tab_close(self, params: dict) -> Tuple[bool, dict]:
        tabs = self._tabs()
        ref = params.get("ref") or getattr(self, "_active_ref", None)
        if ref is None or ref not in tabs:
            return False, {"code": "tab_not_found", "ref": ref}
        closing_active = ref == getattr(self, "_active_ref", None)
        try:
            tabs[ref].page.close()
        except Exception:
            pass
        del tabs[ref]
        if not tabs:  # 保底：至少留一个空白页
            raw = self.page.page.context.new_page()
            tabs[ref or "tab_1"] = PlaywrightPageOps(raw)
        if closing_active:
            first_ref = next(iter(tabs))
            self.page = tabs[first_ref]
            self._active_ref = first_ref
        else:
            self._active_ref = getattr(self, "_active_ref", None) or \
                next(iter(tabs))
        return True, {"closed": ref, "remaining": len(tabs),
                      "active": self._active_ref}

    def _download(self, params: dict) -> Tuple[bool, dict]:
        path = params["path"]
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",
                    exist_ok=True)
        url = params.get("url")
        trigger = params.get("trigger_target")

        if url and url.startswith("data:"):  # 内联数据直链
            _header, _, payload = url.partition(",")
            if "base64" in _header:
                content = base64.b64decode(payload)
            else:
                from urllib.parse import unquote

                content = unquote(payload).encode()
            with open(path, "wb") as f:
                f.write(content)
            return True, {"path": path, "bytes": len(content),
                          "mode": "url"}

        if url:  # 直链模式：携带会话 Cookie
            import httpx

            resp = httpx.get(url, follow_redirects=True, timeout=60.0,
                             cookies={c["name"]: c["value"] for c in
                                      self.page.page.context.cookies()})
            resp.raise_for_status()
            with open(path, "wb") as f:
                f.write(resp.content)
            return True, {"path": path, "bytes": len(resp.content),
                          "mode": "url"}

        if trigger:  # 触发模式：点击引发浏览器下载事件
            with self.page.page.expect_download(timeout=60000) as dl_info:
                self.page.resolve(trigger).click()
            dl = dl_info.value
            dl.save_as(path)
            return True, {"path": path, "mode": "trigger",
                          "suggested": dl.suggested_filename}

        return False, {"code": "missing_param",
                       "detail": "url or trigger_target required"}

    # --- 便捷 -----------------------------------------------------------------
    def navigate(self, url: str, wait_for: str = "networkidle") -> None:
        self.page.goto(url, wait_for)

    def trigger_navigate(self, url: str) -> None:
        """对外触发导航（demo 用）：导航 + 观察 + 发出语义事件。"""
        self.page.goto(url, "networkidle")
        self._observe()



def _jsonable(v):
    """JSON 不可序列化值降级为字符串表示。"""
    try:
        import json as _j

        _j.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)


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