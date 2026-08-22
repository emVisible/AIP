"""apa-sdk: Schema 录制模式（设计文档 §B.1 问题 1）。

降低语义适配器冷启动门槛：Bot 运行时自动记录触发动作的元素与页面
状态，生成 ElementSchema 草稿供人工审核（事件/动作命名需人工确认，
草稿中以 TODO 标注）。

用法：
    recorder = SchemaRecorder()
    executor = BrowserExecutor(..., adapter=..., )
    # 驱动流程（真实浏览器或 MockPage）
    for name, params in executed_actions:
        recorder.record(name, params, page_state)
    recorder.save_draft("schema.draft.yaml")

草稿结构：
    app: {name, url_pattern}
    semantic_patterns:
      recorded_page:            # 页面加载模式
        trigger: {url_pattern}
        emit: {event, data_mapping:{url,title}}
      interaction_<n>:          # 每次交互一个候选模式
        trigger: {element:{role,text_pattern}}
        emit:
          event: "TODO.name.me"           ← 人工命名
          data_mapping: {...}
          available_actions: [{name: TODO, maps_to_action: <recorded action>}]
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

from .semantic_adapter import ScreenState


def _url_glob(url: str) -> str:
    """URL → 保守 glob（保留 host 与首段路径，其余 *）。"""
    m = re.match(r"^(https?://[^/]+(?:/[^/?#]*)?).*$", url or "")
    return (m.group(1) + "*") if m else "*"


def _text_pattern(text: str) -> str:
    """元素文本 → 正则片段（转义 + 空白归一）。"""
    return re.sub(r"\s+", r"\\s*", re.escape(text.strip()))[:60]


class SchemaRecorder:
    def __init__(self, *, app_name: str = "") -> None:
        self.app_name = app_name
        self.pages: List[Dict[str, Any]] = []       # {url,title,glob}
        self.interactions: List[Dict[str, Any]] = []

    # --- 采集 ---------------------------------------------------------------
    def record_page(self, state: ScreenState) -> None:
        glob = _url_glob(state.url or "")
        if any(p["glob"] == glob for p in self.pages):
            return
        self.pages.append({"url": state.url or "", "title": state.title or "",
                           "glob": glob})

    def record_action(self, name: str, params: dict,
                      state: Optional[ScreenState]) -> None:
        """记录一次已执行的动作；尽量从当前页面状态反查目标元素。"""
        target = params.get("target") or ""
        elem: Optional[dict] = None
        if state is not None:
            for e in state.elements:
                if e.data_apa_id == target or e.id == target \
                        or e.text == target:
                    elem = {"role": e.role,
                            "text": e.text,
                            "data_apa_id": e.data_apa_id,
                            "aria_label": e.aria_label}
                    break
        if name.startswith("browser.navigate"):
            if state is not None:
                self.record_page(state)
            return
        verb = name.split(".")[-1]
        self.interactions.append({
            "action": name, "verb": verb, "target": target,
            "params_keys": sorted(k for k in params.keys() if k != "selectors"),
            "element": elem,
            "url": (state.url if state else ""),
        })

    # --- 草稿生成 -------------------------------------------------------------
    def draft(self) -> dict:
        patterns: Dict[str, Any] = {}
        for i, p in enumerate(self.pages):
            patterns[f"recorded_page_{i}"] = {
                "trigger": {"url_pattern": p["glob"]},
                "emit": {
                    "event": "browser.page.loaded",
                    "data_mapping": {
                        "url": {"selector": "__url__"},
                        "title": {"selector": "__title__"},
                    },
                },
            }
        for i, it in enumerate(self.interactions):
            emit: Dict[str, Any] = {
                "event": f"TODO.{it['verb']}.happened",   # 人工命名（§B.1）
            }
            available = []
            if it["element"]:
                trig = {"role": it["element"]["role"]}
                if it["element"].get("text"):
                    trig["text_pattern"] = _text_pattern(it["element"]["text"])
                emit["trigger_element"] = trig
                available.append({
                    "name": f"TODO_{i}_{it['verb']}",
                    "maps_to_action": it["action"],
                })
            elif it["target"]:
                emit["data_mapping"] = {"target_ref":
                                        {"selector": f"[data-apa-id='{it['target']}']"}}
            if available:
                emit["available_actions"] = available
            patterns[f"interaction_{i}"] = {
                "trigger": {"url_pattern": _url_glob(it["url"])},
                "emit": emit,
            }
        app = {"name": self.app_name or "Recorded App"}
        if self.pages:
            app["url_pattern"] = self.pages[0]["glob"]
        return {"app": app, "semantic_patterns": patterns}

    def save_draft(self, path: str) -> str:
        if yaml is None:
            raise RuntimeError("PyYAML is required")
        header = ("# AUTO-GENERATED by APA SchemaRecorder (§B.1) — "
                  "人工审核后再使用：\n"
                  "# · 将 TODO.* 事件/动作名替换为业务语义名\n"
                  "# · 校验 trigger 匹配范围，避免误报\n")
        text = header + yaml.safe_dump(self.draft(),
                                       allow_unicode=True, sort_keys=False)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def summary(self) -> dict:
        return {"pages": len(self.pages), "interactions": len(self.interactions)}