"""apa-core: 浏览器操作录制器（对标影刀录制器 / UiPath Web Recorder）。

三层结构：
  1. 纯函数层：选择器生成 + 事件→步骤转换（无浏览器依赖，可单测）
  2. RecorderSession：Playwright 注入监听脚本，收集用户操作事件
  3. CLI 入口：apa record <url> → 交互式录制 → 导出 process.yaml

用法：
    apa record https://example.com/orders --process-id scrape_orders \\
        --out data/processes/scrape_orders.yaml
在打开的浏览器中点击/输入，关闭窗口即完成录制。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 1. 选择器生成（纯函数）
# ---------------------------------------------------------------------------

def css_selector(el: Dict[str, Any]) -> str:
    """按优先级生成稳健选择器：

    data-apa-id > #id > [name=…] > [aria-label=…] > 标签+类路径
    """
    attrs = el.get("attrs") or {}
    tag = el.get("tag") or "div"

    apa_id = attrs.get("data-apa-id")
    if apa_id:
        return f"[data-apa-id='{apa_id}']"

    el_id = el.get("id")
    if el_id:
        return f"#{el_id}"

    name = attrs.get("name")
    if name:
        return f"[name='{name}']"

    aria = attrs.get("aria-label")
    if aria:
        return f"[aria-label='{aria}']"

    cls = attrs.get("class")
    if cls:
        first = cls.strip().split()[0]
        return f"{tag}.{first}"

    return tag


def event_to_step(ev: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    """单个录制事件 → process 步骤 dict。返回 None 表示跳过。"""
    kind = ev.get("kind")
    step_id = ev.get("step_id") or f"s{idx:02d}_{kind}"

    if kind == "navigate":
        return {
            "id": step_id,
            "action": "browser.navigate",
            "params": {"url": ev.get("url", "")},
        }

    if kind in ("click", "input"):
        target = css_selector(ev.get("element") or {})
        if kind == "click":
            return {
                "id": step_id,
                "action": "browser.click",
                "params": {"target": target},
            }
        value = str(ev.get("value", ""))
        return {
            "id": step_id,
            "action": "browser.input",
            "params": {"target": target, "value": value},
        }

    if kind == "select":
        return {
            "id": step_id,
            "action": "browser.select_option",
            "params": {
                "target": css_selector(ev.get("element") or {}),
                "value": str(ev.get("value", "")),
            },
        }

    return None


def events_to_process(
    events: List[Dict[str, Any]],
    *,
    process_id: str = "recorded_flow",
    trigger_name: Optional[str] = None,
) -> Dict[str, Any]:
    """事件列表 → 完整 process 定义 dict。

    - 合并连续 navigate（只保留最后一条，且仅作为第一步）
    - 输出变量自动编号 output_as
    """
    steps: List[Dict[str, Any]] = []
    idx = 1

    for ev in events:
        if ev.get("kind") == "navigate":
            # 仅首个导航生成步骤（打开页面）；
            # 后续跳转是点击的后果，与影刀录制器语义一致
            if not steps:
                first = event_to_step(ev, idx)
                if first is not None:
                    first["id"] = f"s{idx:02d}_navigate"
                    steps.append(first)
                    idx += 1
            continue
        step = event_to_step(ev, idx)
        if step is not None:
            steps.append(step)
            idx += 1

    proc: Dict[str, Any] = {
        "id": process_id,
        "mode": "process",
        "trigger": (
            {"type": "manual"}
            if not trigger_name else
            {"type": "event", "name": trigger_name}
        ),
        "max_actions": max(len(steps) * 2, 10),
        "steps": steps,
    }
    return {"process": proc}


# ---------------------------------------------------------------------------
# 2. RecorderSession —— Playwright 包装（延迟导入）
# ---------------------------------------------------------------------------

_LISTENER_JS_TMPL = """
(() => {{
  const GEN = {gen};
  function pick(el) {{
    const attrs = {{}};
    for (const a of el.attributes || []) {{
      attrs[a.name] = a.value;
    }}
    // 只保留关键属性，减小传输量
    const keep = {{}};
    for (const k of ['data-apa-id','name','aria-label','class','type','href']) {{
      if (attrs[k] !== undefined) keep[k] = attrs[k];
    }}
    return {{
      tag: el.tagName ? el.tagName.toLowerCase() : 'div',
      id: el.id || '',
      text: (el.innerText || '').slice(0, 60),
      attrs: keep,
    }};
  }}

  const send = (ev) => {{
    try {{ ev.gen = GEN; window.__apa_record(ev); }} catch (_) {{}}
  }};

  // capture 阶段：真实输入与 JS 合成事件都能捕获
  document.addEventListener('click', (e) => {{
    send({{ kind: 'click', element: pick(e.target) }});
  }}, true);

  document.addEventListener('change', (e) => {{
    const t = e.target;
    const kind = t.tagName === 'SELECT' ? 'select' : 'input';
    send({{ kind, element: pick(t), value: t.value || '' }});
  }}, true);
}})();
"""


class RecorderSession:
    """有头浏览器录制会话。close 后 events 可导出。

    注入策略（实证结论）：
      - init_script / document.open() 之前挂的监听器会被 set_content
        与硬导航清除，无法存活；
      - 唯一可靠方式是「页面就绪后 evaluate 注入」；
      - 同一文档多次注入会产生重复监听器 → 用世代号(gen)在 Python 侧
        去重：每次注入 gen+1，旧世代事件丢弃。
    """

    def __init__(self, url: str, headless: bool = False) -> None:
        self.url = url
        self.headless = headless
        self.events: List[Dict[str, Any]] = []
        self._pw = self._browser = self._page = None
        self._gen = 0

    def _on_event(self, ev: Dict[str, Any]) -> None:
        if not isinstance(ev, dict):
            return
        if ev.get("gen", self._gen) != self._gen:
            return  # 旧世代监听器的事件（重复注入残留）→ 丢弃
        self.events.append(ev)

    def start(self) -> None:
        from playwright.sync_api import sync_playwright  # 延迟导入

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()

        self._page.expose_binding("__apa_record",
                                  lambda src, ev: self._on_event(ev))

        def _ensure(*_a) -> None:
            self.reinject()

        self._page.on("load", _ensure)
        self._page.on("domcontentloaded", _ensure)
        self._page.goto(self.url, wait_until="networkidle")
        self.reinject()

    def reinject(self) -> None:
        """注入当前世代的监听器（页面加载/set_content 后调用）。"""
        if self._page is None:
            return
        try:
            self._gen += 1
            self._page.evaluate(_LISTENER_JS_TMPL.format(gen=self._gen))
        except Exception:
            self._gen -= 1

    def wait_until_closed(self) -> None:
        """阻塞直到用户关闭浏览器窗口。"""
        try:
            self._page.wait_for_event("close", timeout=0)
        except Exception:
            pass

    def snapshot_events(self) -> List[Dict[str, Any]]:
        """带导航合并的事件快照：每次 SPA 跳转记录一条 navigate。"""
        nav_url = ""
        out: List[Dict[str, Any]] = []
        try:
            current = self._page.url
        except Exception:
            current = ""
        if current:
            out.append({"kind": "navigate", "url": current})
        out.extend(self.events)
        return out

    def stop(self) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass