"""apa-core: 失败回流诊断（Phase C）——运行失败 → 解释 + 修正建议。

输入：失败会话的 journal 记录子集（action_result failed 条目 +
outcome_summary）。输出：{explanation, suggestion}。

设计约束：
  · 只读分析——不自动修改流程；建议以话术/参数补丁形式给出，
    用户确认后走既有确认门
  · LLM 缺席 → dependency_missing（离线承诺不破坏）
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


class FailureDiagnostic:
    def __init__(self, client) -> None:
        self.client = client

    # ---- journal 解析 -------------------------------------------------------

    @staticmethod
    def extract_failures(records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """从 journal 记录中提取失败上下文。"""
        failed_actions: List[Dict[str, str]] = []
        outcome = None

        for rec in records or []:
            kind = rec.get("kind", "")
            if kind == "action_result" and rec.get("status") not in (
                    "ok", None):
                failed_actions.append({
                    "action": str(rec.get("action_name")
                                   or rec.get("source") or "?"),
                    "status": str(rec.get("status")),
                    "code": str(rec.get("code") or ""),
                    "detail": str(rec.get("detail") or "")[:200],
                })
            elif kind == "outcome_summary":
                outcome = str(rec.get("outcome") or "")

        return {"outcome": outcome or "unknown",
                "failed_actions": failed_actions,
                "failed_count": len(failed_actions)}

    # ---- LLM 解释 ------------------------------------------------------------

    SYSTEM = (
        "你是 RPA 流程失败分析师。输入是一段失败流程的诊断信息。\n"
        '只输出 JSON：{"explanation": "<用中文一句话解释最可能的根因>", '
        '"suggestion": "<给用户的具体修正建议，含可操作的下一步>"}\n'
        "解释要具体到动作名和错误码，不要泛泛而谈。")

    def explain(self, failure_ctx: Dict[str, Any],
                process_yaml: str = "") -> Dict[str, Any]:
        if self.client is None:
            return {"error": "dependency_missing",
                    "detail": "LLM key 未配置"}

        failed = failure_ctx.get("failed_actions") or []
        compact = {
            "outcome": failure_ctx.get("outcome"),
            "failed_steps": [
                {k: v for k, v in f.items() if v}
                for f in failed[:8]
            ],
        }
        user: Dict[str, Any] = {"diagnosis": compact}
        if process_yaml:
            user["process_yaml_head"] = process_yaml[:3000]

        try:
            content = self.client.chat([
                {"role": "system", "content": self.SYSTEM},
                {"role": "user",
                 "content": json.dumps(user, ensure_ascii=False)},
            ])
        except Exception as e:  # noqa: BLE001
            return {"error": f"llm_error:{type(e).__name__}",
                    "detail": str(e)[:120]}

        import re

        m = re.search(r"\{.*\}", content or "", re.DOTALL)
        if not m:
            return {"error": "bad_llm_output"}
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return {"error": "bad_llm_output"}
        return {
            "explanation": str(data.get("explanation", ""))[:500],
            "suggestion": str(data.get("suggestion", ""))[:800],
        }