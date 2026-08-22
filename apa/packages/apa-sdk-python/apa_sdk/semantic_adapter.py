"""apa-sdk: 语义适配器（设计文档 §6）。

Schema-Driven 适配：Executor 启动时声明 ElementSchema，适配器根据
Schema 做模式匹配，把物理世界观察翻译成 AIP 语义事件。新 Executor 通常
只需编写 YAML，无需修改 Python 代码（§6.2）。

元素模型（简化版，覆盖 POC 演示页）：
    Element(role, text, id, data_apa_id, aria_label, attrs)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def parse_int(text: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", str(text))
    return int(digits) if digits else None


def parse_currency(text: str) -> Optional[float]:
    digits = re.sub(r"[^\d.]", "", str(text))
    return float(digits) if digits else None


@dataclass
class Element:
    role: str = ""
    text: str = ""
    id: str = ""
    data_apa_id: str = ""
    aria_label: str = ""
    attrs: Dict[str, str] = field(default_factory=dict)

    def match(self, spec: dict) -> bool:
        if "role" in spec and spec["role"] != self.role:
            return False
        pattern = spec.get("text_pattern")
        if pattern and not re.search(pattern, self.text or ""):
            return False
        if spec.get("text") and spec["text"] not in (self.text or ""):
            return False
        return True


@dataclass
class ScreenState:
    url: str = ""
    title: str = ""
    elements: List[Element] = field(default_factory=list)
    forms: List[dict] = field(default_factory=list)


@dataclass
class SemanticEvent:
    name: str
    data: dict


class SchemaLoadError(ValueError):
    pass


class SemanticAdapter:
    def __init__(
        self,
        schema: Optional[dict] = None,
        *,
        transforms: Optional[Dict[str, Callable[[str], Any]]] = None,
    ) -> None:
        self.schema = schema or {"semantic_patterns": []}
        self.transforms = transforms or {
            "parse_int": parse_int,
            "parse_currency": parse_currency,
            "identity": lambda s: s,
        }

    @classmethod
    def from_yaml(cls, path: str) -> "SemanticAdapter":
        if yaml is None:
            raise RuntimeError("PyYAML is required")
        import pathlib
        return cls(yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")))

    # --- 提升：物理观察 → 语义事件 -------------------------------------------------
    def lift(self, state: ScreenState) -> List[SemanticEvent]:
        events: List[SemanticEvent] = []
        patterns = self.schema.get("semantic_patterns", [])
        if isinstance(patterns, dict):  # 命名模式映射 → 归一化为列表
            patterns = list(patterns.values())
        for pattern in patterns:
            matched = self._match_pattern(pattern, state)
            if matched is None:
                continue
            events.append(self._emit(pattern, matched, state))
        return events

    def _match_pattern(self, pattern: dict, state: ScreenState) -> Optional[List[Element]]:
        trigger = pattern.get("trigger", {})
        # URL 模式（glob）
        url_pattern = trigger.get("url_pattern")
        if url_pattern and not _glob_match(url_pattern, state.url or ""):
            return None
        # 主元素
        elem_spec = trigger.get("element", {})
        candidates = [e for e in state.elements if e.match(elem_spec)]
        if not candidates:
            return None
        # 包含关系：trigger.contains 全部满足
        for sub in trigger.get("contains", []):
            if not any(e.match(sub) for e in state.elements):
                return None
        return candidates

    def _emit(self, pattern: dict, matched: List[Element], state: ScreenState) -> SemanticEvent:
        emit_spec = pattern.get("emit", {})
        data: Dict[str, Any] = {}
        for field, mapping in emit_spec.get("data_mapping", {}).items():
            selector = mapping if isinstance(mapping, str) else mapping.get("selector")
            transform = mapping.get("transform") if isinstance(mapping, dict) else None
            if selector == "__url__":
                value = state.url
            elif selector == "__title__":
                value = state.title
            else:
                value = self._resolve(selector, state.elements)
            if value is not None and transform:
                fn = self.transforms.get(transform)
                if fn:
                    try:
                        value = fn(value)
                    except (ValueError, TypeError):
                        value = None
            data[field] = value
        # available_actions：从当前元素中找可用的动作按钮
        available = []
        for act in emit_spec.get("available_actions", []):
            trig = act.get("trigger", {})
            if any(e.match(trig) for e in state.elements):
                available.append({
                    "name": act.get("name"),
                    "maps_to_action": act.get("maps_to_action"),
                })
        data.setdefault("available_actions", available)
        return SemanticEvent(name=emit_spec.get("event", ""), data=data)

    @staticmethod
    def _resolve(selector: str, elements: List[Element]) -> Optional[str]:
        if not selector:
            return None
        # [attr=val] / [attr]（属性存在即匹配）
        m = re.match(r"^\[([a-z_][a-z0-9_-]*)(?:=([^]]+))?\]$", selector)
        if m:
            attr, want = m.group(1), (m.group(2) or "").strip("'\"")
            for e in elements:
                if attr == "data-apa-id" and e.data_apa_id:
                    if not want or e.data_apa_id == want:
                        return e.text or e.data_apa_id
                val = e.attrs.get(attr)
                if val is not None and (not want or val == want):
                    return val or e.text  # 属性值优先（如 data-order-id）
            return None
        if selector.startswith("#"):
            want = selector[1:]
            for e in elements:
                if e.id == want:
                    return e.text
            return None
        if selector.startswith("."):  # 类选择器
            cls = selector[1:]
            for e in elements:
                if cls in e.attrs.get("class", "").split():
                    return e.text
            return None
        if ":" in selector:
            role, _, text = selector.partition(":")
            for e in elements:
                if e.role == role and text in (e.text or ""):
                    return e.text
            return None
        for e in elements:
            if selector in (e.text or ""):
                return e.text
        return None


def _glob_match(pattern: str, value: str) -> bool:
    """极简 glob：支持 * 与 ?。"""
    regex = "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$"
    return re.match(regex, value) is not None