"""apa-executors: llm.* 文本任务动作（非决策——普通流程步骤）。

动作域：llm.text
  task=classify  {labels:[...]}        → {label, confidence_note}
  task=extract   {fields:[...]}        → {values:{field: str}}
  task=summarize {max_chars?}          → {summary}

默认模型 deepseek-chat；独立于 ai_decision 预算（普通步骤语义）。
密钥经 LLMClient 环境约定注入；缺失时返回 dependency_missing，
流程可走 error_handlers 降级（离线承诺不被破坏）。
"""
from __future__ import annotations

import json
from typing import Tuple

TASKS = ("classify", "extract", "summarize")


class LlmTextExecutor:
    """轻量执行器：不继承 AIPExecutor（无 context/事件需求）。"""

    def __init__(self, source: str, session_id: str, *, client=None,
                 context_store=None) -> None:
        from .llm import LLMClient  # noqa: F401  (可用性探测)

        self._client = client
        self.source = source
        self.session_id = session_id
        self.context_store = context_store
        if self._client is None:
            from .config import env_first

            key = env_first("APA_LLM_API_KEY", "DEEPSEEK_API_KEY")
            if not key or key.strip().startswith("#"):
                self._client = None
            else:
                self._client = LLMClient(timeout_s=30.0)

    def start_observation(self) -> None:
        pass

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        if name != "llm.text":
            return False, {"code": "action_not_supported_by_executor"}
        if self._client is None:
            return False, {"code": "dependency_missing",
                           "detail": "LLM key 未配置（离线模式）",
                           "hint": "设置 DEEPSEEK_API_KEY 或走 HITL 降级"}
        try:
            return self._run(params)
        except Exception as e:  # noqa: BLE001
            return False, {"code": type(e).__name__, "detail": str(e)[:120]}

    # ---- 任务实现 ------------------------------------------------------------

    SYSTEM = {
        "classify": (
            "你是文本分类器。只输出 JSON："
            '{"label":"<从 labels 中选一个>"}'),
        "extract": (
            '你是信息抽取器。只输出 JSON：{"values":{"<field>":"<值>"}}，'
            "无法提取的字段值为 null"),
        "summarize": (
            '你是摘要器。只输出 JSON：{"summary":"<摘要文本>"}'),
    }

    def _run(self, p: dict) -> Tuple[bool, dict]:
        task = p.get("task", "")
        if task not in TASKS:
            return False, {"code": f"unknown task {task!r}"}
        text = str(p.get("input", ""))
        if not text.strip():
            return False, {"code": "missing_param", "detail": "input"}

        user_req: dict = {"task": task}
        if task == "classify":
            labels = p.get("labels") or []
            if not labels:
                return False, {"code": "missing_param", "detail": "labels"}
            user_req["labels"] = list(labels)
        if p.get("instruction"):
            user_req["instruction"] = str(p["instruction"])
        user_req["input"] = text[:8000]

        content = self._client.chat([
            {"role": "system",
             "content": self.SYSTEM[task] +
                        (f" 额外要求：{p['instruction']}"
                         if p.get("instruction") else "")},
            {"role": "user", "content": json.dumps(user_req,
                                                   ensure_ascii=False)},
        ])
        data = _parse_json(content)

        out: dict = {}
        if task == "classify":
            label = data.get("label") if isinstance(data, dict) else None
            if label not in (p.get("labels") or []):
                return False, {"code": "label_out_of_range",
                               "got": label,
                               "allowed": p.get("labels")}
            out["label"] = label
        elif task == "extract":
            values = data.get("values") if isinstance(data, dict) else None
            fields = p.get("fields") or []
            values = values if isinstance(values, dict) else {}
            out["values"] = {f: values.get(f) for f in fields}
        else:
            summary = (data.get("summary")
                       if isinstance(data, dict) else None)
            if not summary:
                return False, {"code": "bad_summary"}
            max_chars = int(p.get("max_chars", 500))
            out["summary"] = str(summary)[:max_chars]

        ref = p.get("output_context")
        if ref and self.context_store is not None:
            r = self.context_store.make_ref(self.session_id, str(ref))
            self.context_store.put(r, out)
        return True, out


def _parse_json(text: str):
    """防御性取首个 {...}；失败返回 {}。"""
    import re as _re

    m = _re.search(r"\{.*\}", text or "", _re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}
