"""apa-core: LLM 决策接口（设计文档 §7.2 L1/L2，§7.3）。

OpenAI-compatible chat.completions 客户端（默认指向 DeepSeek API）。
环境变量：
    APA_LLM_BASE_URL  默认 https://api.deepseek.com
    APA_LLM_API_KEY   必填（无 Key 时仅 FakeLLMClient 可用）
    APA_LLM_MODEL     默认 deepseek-chat

决策协议（对模型的输出约束，DE-3/C3 友好）：
    {"action": "<registry 内动作名>", "target"?: "...", "params"?: {...}}
    {"uncertain": "<原因>"}          → 上层走 DE-5 人工升级
模型永远不能携带 idempotency/risk —— Gateway 校验链兜底（P2）。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

DECISION_SYSTEM_PROMPT = """You are the decision engine of an enterprise RPA system (APA).
You receive ONE semantic event (business fact, never raw UI/DOM/screenshot data)
and must output exactly one decision.

Output ONLY a single JSON object, no prose, no code fences:
  {"action": "<name>", "target": "<optional>", "params": {…}}
or, when you cannot decide safely:
  {"uncertain": "<short reason>"}

Hard rules:
- Choose `action` ONLY from the provided allowed_actions list. Never invent names.
- Never include idempotency or risk in the output (they live in the Action Registry).
- Keep params minimal; reference context via refs when fields are unknown.
- If the event is ambiguous, low-confidence, or outside your knowledge,
  prefer {"uncertain": …} over guessing."""


class LLMError(RuntimeError):
    pass


class LLMClient:
    """同步 OpenAI-compatible 客户端（httpx）。decide() 返回解析后的决策 dict。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("APA_LLM_BASE_URL")
                         or "https://api.deepseek.com").rstrip("/")
        self.api_key = api_key or os.environ.get("APA_LLM_API_KEY", "")
        self.model = model or os.environ.get("APA_LLM_MODEL", "deepseek-chat")
        self.timeout_s = timeout_s
        if not self.api_key:
            raise LLMError("APA_LLM_API_KEY not set (or pass api_key=...)")

    # --- 低层 -----------------------------------------------------------------
    def chat(self, messages: List[dict], *, temperature: float = 0.0) -> str:
        import httpx
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages,
                  "temperature": temperature},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # --- 决策 -------------------------------------------------------------------
    def decide(
        self,
        *,
        event_name: str,
        event_data: Optional[dict],
        allowed_actions: List[str],
        context_summary: Optional[Dict[str, Any]] = None,
        think: bool = False,
    ) -> Dict[str, Any]:
        """一次事件 → 一个决策。失败/越权输出统一折叠为 {"uncertain": ...}。"""
        user = {
            "event": event_name,
            "data": event_data or {},
            "allowed_actions": allowed_actions,
        }
        if context_summary:
            user["context"] = context_summary
        try:
            content = self.chat([
                {"role": "system", "content": DECISION_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ])
        except Exception as e:  # 网络/配额等 → 不猜测，转人工
            return {"uncertain": f"llm_error: {type(e).__name__}"}
        return parse_decision(content)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_decision(content: str) -> Dict[str, Any]:
    """防御性解析模型输出。任何不合规输出都折叠为 uncertain。"""
    if not content:
        return {"uncertain": "empty_response"}
    candidates = [content.strip()]
    m = _JSON_RE.search(content)
    if m:
        candidates.insert(0, m.group(0))
    obj = _SENTINEL = object()
    for cand in candidates:
        try:
            obj = json.loads(cand)
            break
        except ValueError:
            continue
    if obj is _SENTINEL or not isinstance(obj, dict):
        if obj is _SENTINEL:
            return {"uncertain": "no_json"}
        return {"uncertain": "not_object"}
    if "uncertain" in obj:
        return {"uncertain": str(obj["uncertain"])[:200]}
    action = obj.get("action")
    if not isinstance(action, str) or not action:
        return {"uncertain": "missing_action"}
    params = obj.get("params") or {}
    if not isinstance(params, dict):
        return {"uncertain": "bad_params"}
    out: Dict[str, Any] = {"action": action, "params": params}
    target = obj.get("target")
    if isinstance(target, str) and target:
        out["target"] = target
    return out


class FakeLLMClient:
    """测试用：脚本化响应队列 + 调用记录。"""

    def __init__(self, responses: Optional[List[Dict[str, Any]]] = None) -> None:
        self.responses: List[Dict[str, Any]] = list(responses or [])
        self.calls: List[dict] = []

    def decide(self, **kw) -> Dict[str, Any]:
        self.calls.append(kw)
        if self.responses:
            return self.responses.pop(0)
        return {"uncertain": "fake_exhausted"}
