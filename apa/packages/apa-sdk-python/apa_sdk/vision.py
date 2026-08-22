"""apa-sdk: VLM 视觉适配层（设计文档 §5.5，约束 C6）。

VLM 是 Executor 内部的感知手段：截图 → 本地分析 → 语义元素列表。
此类不发出任何 AIP 消息；bounds 坐标保留在 Executor 内存，
进入协议前被剥离（C6）。

实现：
    OpenAICompatibleVisionAdapter — OpenAI-compatible chat completions
    （image_url + json_object 输出），环境变量：
        APA_VISION_BASE_URL  默认 https://api.deepseek.com
        APA_VISION_API_KEY   必填（无 Key 时用 FakeVisionAdapter 测试）
        APA_VISION_MODEL     默认由服务商决定

    FakeVisionAdapter — 脚本化响应（测试/无 Key 演示）。
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Dict, List, Optional

from .semantic_adapter import Element


class VisionError(RuntimeError):
    pass


SCREEN_UNDERSTANDING_PROMPT = """You analyze a screenshot of a business application.
List every interactive element you can see (buttons, links, inputs, headings,
tables, dialogs). Output ONLY JSON:
{"elements": [{"role": "button|link|textbox|heading|dialog|table|cell",
               "text": "<visible text>",
               "data_apa_id": "<if visible>",
               "aria_label": "<if present>",
               "bounds": {"x": 0, "y": 0, "w": 0, "h": 0}}]}
Rules: roles must come from the listed set; keep text short and exact;
include bounds in CSS pixels; never invent elements."""


class VisionAdapter:
    """Executor 本地 VLM 适配层基类。"""

    has_vlm: bool = False

    def understand_screen(self, screenshot: bytes) -> List[Element]:
        raise NotImplementedError


class OpenAICompatibleVisionAdapter(VisionAdapter):
    has_vlm = True

    def __init__(self, *, base_url: Optional[str] = None,
                 api_key: Optional[str] = None,
                 model: Optional[str] = None,
                 timeout_s: float = 30.0) -> None:
        from apa_core.config import env_first
        self.base_url = (base_url
                         or env_first("APA_VISION_BASE_URL", "DEEPSEEK_BASE_URL")
                         or "https://api.deepseek.com").rstrip("/")
        self.api_key = api_key or env_first("APA_VISION_API_KEY",
                                            "DEEPSEEK_API_KEY")
        self.model = model or env_first("APA_VISION_MODEL",
                                        "DEEPSEEK_VISION_MODEL",
                                        "deepseek-vl2")
        if not self.model:
            raise VisionError("APA_VISION_MODEL is required")
        if not self.api_key:
            raise VisionError("APA_VISION_API_KEY is required "
                              "(or use FakeVisionAdapter)")
        self.timeout_s = timeout_s

    def understand_screen(self, screenshot: bytes) -> List[Element]:
        import httpx
        b64 = base64.b64encode(screenshot).decode()
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url":
                                {"url": f"data:image/png;base64,{b64}"}},
                            {"type": "text",
                             "text": SCREEN_UNDERSTANDING_PROMPT},
                        ],
                    }],
                },
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:  # 网络/配额 → 感知失败由调用方降级处理
            raise VisionError(f"vision request failed: {e}") from e
        return parse_vision_elements(content)


_JSON_RE = re.compile(r"\{[\s\S]*\}")
_ALLOWED_ROLES = {"button", "link", "textbox", "heading", "dialog",
                  "table", "cell", "label", "row"}


def parse_vision_elements(content: str) -> List[Element]:
    """防御性解析 VLM 输出 → Element 列表（bounds 保留在本地）。"""
    m = _JSON_RE.search(content or "")
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
        raw_items = obj.get("elements") or []
        if not isinstance(raw_items, list):
            return []
        elements: List[Element] = []
        for item in raw_items[:100]:  # 上限防滥用
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).lower()
            if role not in _ALLOWED_ROLES:
                continue
            bounds = item.get("bounds")
            elements.append(Element(
                role=role,
                text=str(item.get("text", ""))[:200],
                data_apa_id=str(item.get("data_apa_id", "") or ""),
                aria_label=str(item.get("aria_label", "") or ""),
                attrs={},
                bounds=bounds if isinstance(bounds, dict) else None,
            ))
        return elements
    except ValueError:
        return []


class FakeVisionAdapter(VisionAdapter):
    """脚本化视觉结果（测试 / 无 Key 环境）。"""

    has_vlm = True

    def __init__(self, responses: Optional[List[List[Element]]] = None) -> None:
        self.responses: List[List[Element]] = list(responses or [])
        self.calls: List[int] = []

    def understand_screen(self, screenshot: bytes) -> List[Element]:
        self.calls.append(len(screenshot))
        if self.responses:
            return self.responses.pop(0)
        return []