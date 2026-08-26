"""apa-core: 浏览器元素拾取服务（影刀式「从页面选取」）。

架构：
  有窗 Chromium（Playwright，headless=False）打开 URL
    → 注入 picker 脚本：hover 高亮轮廓 + 点击选取（阻止默认跳转）+ Esc 取消
    → expose_binding 回传 {tag, text, css} 到 Python 侧 latest 缓存
  GET /api/browser_pick/result 由前端轮询消费

设计约束：
  - playwright 延迟导入（与 recorder 一致），缺失时给可读错误
  - 单会话模型：重复 start 先静默停掉旧会话
  - SPA 导航后自动重注入（page load 事件钩子）
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None  # type: ignore


class BrowserPickError(RuntimeError):
    pass


# 注入页面的拾取脚本：hover 高亮、点击生成唯一 css 选择器并回传
_PICKER_JS = """
() => {
  if (window.__apa_picker_active) return;
  window.__apa_picker_active = true;
  let last = null;
  function clear() {
    if (last) { last.style.outline = last.__apaPrevOutline || ''; last = null; }
  }
  function buildCss(el) {
    var parts = [];
    var node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
      if (node.id) {
        parts.unshift(node.tagName.toLowerCase() + '#' +
          CSS.escape(node.id));
        break;
      }
      var k = 1, s = node.previousElementSibling;
      while (s) { if (s.tagName === node.tagName) k++; s =
        s.previousElementSibling; }
      parts.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + k + ')');
      node = node.parentElement;
    }
    if (!parts.length) parts.push('body');
    return parts.join(' > ');
  }
  document.addEventListener('mousemove', function(e) {
    var t = e.target;
    if (!t || !t.tagName || t === last) return;
    clear();
    last = t;
    last.__apaPrevOutline = t.style.outline;
    t.style.outline = '2px solid #7c3aed';
  }, true);
  document.addEventListener('click', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var el = e.target;
    window.__apa_pick_callback({
      tag: el.tagName.toLowerCase(),
      text: ((el.innerText || el.value || '') + '').trim().slice(0, 60),
      css: buildCss(el),
    });
  }, true);
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') window.__apa_pick_callback(null);
  }, true);
}
"""


class BrowserPickerService:
    """浏览器元素拾取会话。进程内单例由 API 层持有。

    双通道会话：
      playwright —— start(url) 有窗注入（次要入口）
      extension  —— Chrome 扩展内容脚本经 /api/browser_pick/event 回传
    两者共享同一 latest 缓存，result() 消费方无感。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pw = None
        self._browser = None
        self._page = None
        self._latest: Optional[Dict[str, Any]] = None
        self._version = 0
        self._active = False
        self.started_at = 0.0
        self.last_error: Optional[str] = None

    # ---- 状态 ---------------------------------------------------------------

    def result(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active": self._active,
                "picked": self._latest,
                "version": self._version,
                "error": self.last_error,
            }

    def ingest(self, payload: Dict[str, Any]) -> None:
        """扩展回传通道：内容脚本点选结果写入 latest。"""
        with self._lock:
            self._latest = payload if isinstance(payload, dict) else None
            self._version += 1
            self._active = True
            self.started_at = time.time()

    # ---- 生命周期 -----------------------------------------------------------

    def start(self, url: str) -> Dict[str, Any]:
        if sync_playwright is None:
            raise BrowserPickError(
                "playwright 未安装：pip install playwright "
                "&& playwright install chromium")
        if not url.startswith(("http://", "https://")):
            raise BrowserPickError("URL 必须以 http(s):// 开头")
        with self._lock:
            self._stop_locked()
            try:
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(headless=False)
                page = self._browser.new_page()
                # 绑定回调先于导航，保证首屏点击即可回传
                page.expose_binding("__apa_pick_callback",
                                    self._on_pick)
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.evaluate(_PICKER_JS)
                page.on("load",
                        lambda _p: self._safe_inject(page))
                self._page = page
                self._latest = None
                self._version += 1
                self._active = True
                self.started_at = time.time()
                self.last_error = None
                return {"ok": True}
            except Exception as e:
                self._stop_locked()
                self.last_error = str(e)
                raise BrowserPickError(f"启动拾取浏览器失败: {e}") from e

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    # ---- 内部 ---------------------------------------------------------------

    def _on_pick(self, _source: Any, payload: Any) -> None:
        with self._lock:
            self._latest = payload if isinstance(payload, dict) else None
            self._version += 1

    def _safe_inject(self, page: Any) -> None:
        try:
            page.evaluate(_PICKER_JS)
        except Exception:
            pass  # 页面正在跳转等瞬态失败可忽略

    def _stop_locked(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._browser = None
        self._pw = None
        self._page = None
        self._active = False
