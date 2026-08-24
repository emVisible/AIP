"""apa-core: IntentCompiler —— 自然语言 → process.yaml 草稿（Phase B）。

双环架构的意图合成环：
  · 能力目录 = Action Registry（动作名+description+when_to_use 注解
    作为 LLM 的 tool catalog）
  · 策略一（本版）：模板检索+槽位填充 —— 从场景模板库检索最相近
    骨架，LLM 只负责 (a) 选模板 (b) 填槽参数 (c) 生成澄清问题
  · 硬约束：产出 steps 中出现的 action 必须 ∈ Registry，
    否则编译失败并返回澄清问题（幻觉防线）
  · 输出永远带 needs_clarification / questions 字段——确认门协议
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CompileResult:
    ok: bool
    process_yaml: Optional[str] = None
    template_id: Optional[str] = None
    questions: List[str] = field(default_factory=list)
    error: Optional[str] = None
    raw_llm: Optional[str] = None


class IntentCompiler:
    """模板检索 + 槽位填充式意图编译器（策略一）。

    templates: {template_id: {"keywords": [...], "slots": [...],
                               "yaml": str}}   # yaml 含 {{slot}} 占位
    """

    def __init__(self, templates: Dict[str, Dict[str, Any]],
                 client) -> None:
        self.templates = templates
        self.client = client          # LLMClient（或同 decide/chat 面）

    # ---- 模板检索 -----------------------------------------------------------

    def _score_template(self, text: str,
                        tpl: Dict[str, Any]) -> Tuple[int, int]:
        kw = [k.lower() for k in tpl.get("keywords", [])]
        tl = text.lower()
        hits = sum(1 for k in kw if k and k in tl)
        return hits, len(kw)

    def pick_template(self, utterance: str) -> Tuple[Optional[str], float]:
        scored = []
        for tid, tpl in self.templates.items():
            hits, total = self._score_template(utterance, tpl)
            if hits:
                scored.append((hits / max(total, 1), tid))
        if not scored:
            return None, 0.0
        scored.sort(reverse=True)
        best_ratio, best_id = scored[0]
        return best_id, best_ratio

    # ---- 槽位填充 -----------------------------------------------------------

    def _fill_prompt(self, utterance: str,
                     tpl: Dict[str, Any]) -> str:
        slots = tpl.get("slots", [])
        sysmsg = (
            "你是 RPA 流程槽位填充器。根据用户话术为模板填槽。"
            "只输出 JSON：{\"filled\": {\"<slot>\": \"<值>\"}, "
            "\"questions\": [\"<缺失信息追问>\"]}"
            "——值无法从话术确定的 slot 放入 questions 追问。")
        user = json_dumps_cn({
            "utterance": utterance,
            "template": tpl.get("description", ""),
            "slots": slots,
            "current_yaml": tpl.get("yaml", ""),
        })
        return f"{sysmsg}\n\n{user}"

    def compile(self, utterance: str) -> CompileResult:
        text = utterance.strip()
        if not text:
            return CompileResult(ok=False,
                                 error="empty utterance",
                                 questions=["请描述你想自动化的任务"])

        tid, ratio = self.pick_template(text)
        if tid is None:
            return CompileResult(ok=False, error="no_template_match",
                                 questions=[
                                     "暂无匹配场景模板。可尝试描述："
                                     "价格监控 / 数据日报 / 库存预警 / "
                                     "批量改价 / 客服质检 / 订单回传"])
        tpl = self.templates[tid]

        prompt = self._fill_prompt(text, tpl)
        try:
            content = self.client.chat([
                {"role": "system", "content":
                    "只输出单个 JSON 对象，不要散文。"},
                {"role": "user", "content": prompt},
            ])
        except Exception as e:  # noqa: BLE001
            return CompileResult(ok=False, error=f"llm_error:{e}",
                                 questions=["LLM 调用失败，请稍后重试"])

        parsed = extract_json(content)
        filled: Dict[str, Any] = parsed.get("filled") or {}
        questions: List[str] = list(parsed.get("questions") or [])

        yaml_text = tpl.get("yaml", "")
        for slot, value in filled.items():
            yaml_text = re.sub(rf"\{{{{\s*{re.escape(slot)}\s*\}}}}",
                                str(value), yaml_text)

        missing = [s for s in tpl.get("slots", [])
                   if re.search(rf"\{{{{\s*{re.escape(s)}\s*\}}}}",
                                 yaml_text)]
        if missing:
            for m in missing:
                q = f"请提供「{m}」"
                if q not in questions:
                    questions.append(q)

        if questions:
            return CompileResult(ok=False, template_id=tid,
                                 questions=questions,
                                 raw_llm=content)

        return CompileResult(ok=True, process_yaml=yaml_text,
                             template_id=tid, questions=[], raw_llm=content)


def json_dumps_cn(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=1)


def extract_json(text: str) -> Dict[str, Any]:
    """防御性取首个 {...}；失败返回 {}。"""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {}
    try:
        obj = __import__("json").loads(m.group(0))
        return obj if isinstance(obj, dict) else {}
    except ValueError:
        return {}
