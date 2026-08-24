"""apa-core: 自由编译器（Phase B 策略二）。

全 Action Registry 作为 LLM 词表，从任意自然语言组装 process.yaml。
三重防线：
  1. 动作名必须 ∈ Registry（幻觉动作直接拒绝并转澄清）
  2. 结构校验：build_process 试编译（steps 非空/id 唯一/C3 键检查）
  3. 不确定信息强制进 questions 而非编造（prompt 层约定 + 兜底）

输出与模板策略同构的 CompileResult —— API 层零改动。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .compiler import CompileResult, json_dumps_cn


def _extract_json(text: str) -> Dict[str, Any]:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else {}
    except ValueError:
        return {}


class FreeIntentCompiler:
    """自由编译：Registry 词表 + LLM 组装 + 双重校验。"""

    def __init__(self, registry, client, *,
                 max_actions_cap: int = 500,
                 catalog_max_chars: int = 24000) -> None:
        self.reg = registry
        self.client = client
        self.max_actions_cap = int(max_actions_cap)
        self.catalog_max_chars = int(catalog_max_chars)

    # ---- 词表构建 -----------------------------------------------------------

    def catalog(self) -> List[Dict[str, str]]:
        """紧凑动作目录：name/description/risk/required 参数。"""
        out: List[Dict[str, str]] = []
        for name in sorted(self.reg.names()):
            e = self.reg.get(name)
            if e is None:
                continue
            required: List[str] = []
            params = e.params or {}
            if isinstance(params, dict):
                req = params.get("required")
                if isinstance(req, list):
                    required = [str(x) for x in req]
            out.append({
                "name": name,
                "desc": (e.description or "")[:120],
                "risk": e.risk,
                "required": ",".join(required),
            })
        return out

    def _catalog_text(self) -> str:
        lines = []
        budget = self.catalog_max_chars
        for it in self.catalog():
            line = (f"- {it['name']} | risk={it['risk']} | "
                    f"必填[{it['required']}] | {it['desc']}")
            if len(line) > budget:
                break
            budget -= len(line) + 1
            lines.append(line)
        return "\n".join(lines)

    # ---- 校验 ---------------------------------------------------------------

    @staticmethod
    def _validate(proc: Dict[str, Any], reg_names: set) -> Tuple[
            List[str], List[str]]:
        """返回 (errors, questions)。结构错误→errors；信息缺口→questions。"""
        errors: List[str] = []
        questions: List[str] = []

        p = proc.get("process") if isinstance(
            proc.get("process"), dict) else proc
        steps = p.get("steps") if isinstance(p, dict) else None
        if not isinstance(steps, list) or not steps:
            errors.append("steps 为空——至少需要一个执行步骤")
            return errors, questions

        ids = [s.get("id") for s in steps if isinstance(s, dict)]
        if len(ids) != len(set(ids)):
            errors.append("步骤 id 重复")

        for s in steps:
            if not isinstance(s, dict):
                continue
            act = s.get("action")
            stype = s.get("type")
            if stype in ("foreach", "while"):
                continue                      # 控制容器递归由引擎校验
            if stype in ("loop.break", "loop.continue",
                          "ai_decision", "log"):
                continue                      # 引擎内建类型
            if not act:
                errors.append(f"步骤 {s.get('id')!r} 缺少 action")
            elif act not in reg_names:
                # 幻觉动作 = 硬拒绝：执行必然被 Gateway 拒绝，
                # 同时转澄清让用户选择替代实现
                errors.append(f"unknown action {act!r}")
                questions.append(
                    f"动作 {act!r} 不存在——"
                    "请说明想达成的效果，我会用已有动作重新编排")
        return errors, questions

    # ---- 编译 -----------------------------------------------------------------

    SYSTEM = (
        "你是企业 RPA 流程编译器：把用户意图编译为 APA 流程 JSON。\n"
        "只输出单个 JSON 对象：\n"
        '{"questions": ["<缺失信息的追问>"], '
        '"process": {"id":"<kebab-id>","mode":"process",'
        '"trigger":{"type":"manual"},"max_actions":<int>,"steps":[...]}}\n'
        "硬性规则：\n"
        "1. steps[].action 只能取目录中列出的名字，禁止发明\n"
        "2. 信息不足时不要编造参数值——写进 questions 追问\n"
        '3. 每个步骤必须有唯一 id；params 用真实值或 "{{ref}}" 模板\n'
        "4. max_actions ≥ 步骤数×2\n"
        "5. 循环用 type=foreach(params.source/item_var/body_action/"
        "body_params)；条件分支用 step.condition")

    def compile(self, utterance: str) -> CompileResult:
        text = (utterance or "").strip()
        if not text:
            return CompileResult(ok=False, error="empty utterance",
                                 questions=["请描述任务"])
        cat = self._catalog_text()

        user = json_dumps_cn({
            "utterance": text,
            "action_catalog": "\n" + cat,
            "max_actions_cap": self.max_actions_cap,
        })
        try:
            content = self.client.chat([
                {"role": "system", "content": self.SYSTEM},
                {"role": "user", "content": user},
            ])
        except Exception as e:  # noqa: BLE001
            return CompileResult(ok=False, error=f"llm_error:{e}",
                                 questions=["LLM 调用失败，请稍后重试"])

        parsed = _extract_json(content)
        questions = [str(q)[:200] for q in (parsed.get("questions") or [])]
        proc = parsed.get("process")

        if not isinstance(proc, dict):
            return CompileResult(ok=False, error="no_process_in_response",
                                 questions=questions or [
                                     "无法从描述确定流程步骤，"
                                     "请更具体地说明要操作的系统与动作"],
                                 raw_llm=content)

        # 硬校验①：结构 + 动作名 ∈ Registry（精确错误优先于泛化文案）
        reg_names = set(self.reg.names())
        errors, qs2 = self._validate(proc, reg_names)
        questions.extend(qs2)
        if errors:
            return CompileResult(ok=False,
                                 error="invalid_process:" +
                                        "; ".join(errors[:3]),
                                 questions=questions or [
                                     "流程结构未通过校验，请补充或修正描述"],
                                 raw_llm=content)

        # 硬校验②：结构可编译（C3/唯一 id/预算等全部走既有解析器）
        import yaml as _yaml

        from ..process import ProcessDefinitionError, build_process

        yaml_text = _yaml.safe_dump({"process": proc}, allow_unicode=True,
                                     sort_keys=False)
        try:
            build_process({"process": proc})
        except Exception as e:  # noqa: BLE001
            return CompileResult(ok=False,
                                 error=f"build_failed:{e}"[:300],
                                 questions=questions or [
                                     "流程定义不合法，请调整描述"],
                                 raw_llm=content)

        # 预算上限钳位
        cap = self.max_actions_cap
        ma = int(proc.get("max_actions") or 0)
        if ma <= 0 or ma > cap:
            proc["max_actions"] = min(max(ma, len(proc["steps"]) * 2, 10),
                                       cap)
            yaml_text = _yaml.safe_dump({"process": proc},
                                         allow_unicode=True,
                                         sort_keys=False)

        return CompileResult(ok=True, process_yaml=yaml_text,
                             template_id=None, questions=[],
                             raw_llm=content)


class AutoIntentCompiler:
    """自动路由：模板命中走策略一，否则自由编译。"""

    def __init__(self, template_compiler, free_compiler) -> None:
        self.template = template_compiler
        self.free = free_compiler

    def compile(self, utterance: str) -> CompileResult:
        tid, _ratio = self.template.pick_template(utterance or "")
        if tid is not None:
            return self.template.compile(utterance)
        return self.free.compile(utterance)