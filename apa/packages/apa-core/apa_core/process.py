"""apa-core: Process Mode 流程编排引擎（设计文档 §10.2 模式 B）。

步骤固定、合规要求严格的场景。流程以 Decision Engine 身份驱动同一
Gateway 校验链（P2：AI/流程都不持有执行权；C3：idempotency/risk 只在
Registry）。

定义（YAML）：
    process:
      id: po_auto_approval
      mode: process
      trigger: { type: event, name: erp.order.approval_requested }
      timeout_minutes: 60
      steps:
        - id: fetch_detail
          action: context.get
          params: { ref: "{{ event.data.context }}", fields: [amount] }
          output_as: order
          on_failure: { goto: escalate }
        - id: ai_decision
          type: ai_decision            # 由 DecisionEngine 插槽决策
          context: ["{{ steps.order }}"]
          available_actions: [approve_order, reject_order]
        - id: approve_order
          condition: "{{ steps.ai_decision.outcome == 'approve_order' }}"
          action: erp.order.approve
          params: { order_id: "{{ steps.order.order_id }}" }
      error_handlers:
        escalate:
          action: human.task.create
          params: { task_type: exception, assignee_role: ops }

模板上下文：
    event.*      触发事件的 name/data
    steps.<id>.* 该步骤输出（action 结果 data 或 ai_decision 的 outcome）
    error.*      { reason }（on_failure 跳转时注入）

约束：steps 中不允许出现 idempotency / risk 键（C3，加载即拒绝）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
FORBIDDEN_KEYS = {"idempotency", "risk"}  # C3


class ProcessDefinitionError(ValueError):
    pass


def lookup(path: str, scopes: Dict[str, Any]) -> Any:
    value: Any = scopes
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def render(value: Any, scopes: Dict[str, Any]) -> Any:
    """整值模板保留原生类型；混合字符串做子串替换。"""
    if isinstance(value, str):
        m = TEMPLATE_RE.fullmatch(value)
        if m:
            native = lookup(m.group(1), scopes)
            return value if native is None else native
        return TEMPLATE_RE.sub(
            lambda mm: str(lookup(mm.group(1), scopes)), value)
    if isinstance(value, dict):
        return {k: render(v, scopes) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, scopes) for v in value]
    return value


@dataclass
class StepDef:
    id: str
    action: Optional[str] = None
    type: Optional[str] = None                 # ai_decision / foreach / sub_process
    params: dict = field(default_factory=dict)
    target: Optional[str] = None
    condition: Optional[str] = None            # Python 表达式（受限 eval）
    output_as: Optional[str] = None
    on_failure: Optional[dict] = None          # { goto: step_id }
    expect_event: Optional[str] = None
    body_steps: List[Dict[str, Any]] = field(default_factory=list)  # foreach 子步骤


@dataclass
class ProcessDef:
    process_id: str
    mode: str
    trigger_name: Optional[str]
    timeout_minutes: int
    max_actions: int
    steps: List[StepDef]
    error_handlers: Dict[str, StepDef]


def load_process(path: str | "Path") -> ProcessDef:  # noqa: F821
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    from pathlib import Path as _Path
    data = yaml.safe_load(_Path(path).read_text(encoding="utf-8"))
    return build_process(data)


def build_process(data: dict) -> ProcessDef:
    proc = data.get("process") or {}
    pid = proc.get("id")
    if not pid:
        raise ProcessDefinitionError("process.id is required")
    steps_raw = proc.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ProcessDefinitionError(f"{pid}: steps must be a non-empty list")

    def to_step(raw: dict) -> StepDef:
        bad = FORBIDDEN_KEYS & set(raw.keys())
        if bad:
            raise ProcessDefinitionError(
                f"{pid}: step carries {sorted(bad)} — C3 forbids "
                "(declare in Action Registry instead)")
        for key in ("params", "output_as", "condition", "target"):
            if isinstance(raw.get(key), dict):
                nested_bad = FORBIDDEN_KEYS & set(raw[key].keys())
                if nested_bad:
                    raise ProcessDefinitionError(
                        f"{pid}: {sorted(nested_bad)} inside step payload (C3)")
        return StepDef(
            id=raw.get("id") or "",
            action=raw.get("action"),
            type=raw.get("type"),
            params=raw.get("params") or {},
            target=raw.get("target"),
            condition=raw.get("condition"),
            output_as=raw.get("output_as"),
            on_failure=raw.get("on_failure"),
            expect_event=raw.get("expect"),
        )

    steps = [to_step(s) for s in steps_raw]
    ids = [s.id for s in steps]
    if len(set(ids)) != len(ids):
        raise ProcessDefinitionError(f"{pid}: duplicate step ids")
    handlers = {k: to_step(v) for k, v in (proc.get("error_handlers") or {}).items()}
    trigger = proc.get("trigger") or {}
    return ProcessDef(
        process_id=pid,
        mode=proc.get("mode", "process"),
        trigger_name=trigger.get("name"),
        timeout_minutes=int(proc.get("timeout_minutes", 60)),
        max_actions=int(proc.get("max_actions", 100)),
        steps=steps,
        error_handlers=handlers,
    )


_SAFE_EVAL_GLOBALS = {"__builtins__": {}}


class _NS(dict):
    """字典的点访问视图：steps.order.amount 可在表达式中直接求值。"""

    def __getattr__(self, k):
        try:
            v = self[k]
        except KeyError:
            raise AttributeError(k)
        return _NS(v) if isinstance(v, dict) else v


# 条件表达式 AST 白名单：仅比较 / 布尔运算 / 点路径 / 字面量。
# 禁止 Call/Subscript 等（正则无法可靠拦截 __import__ 等绕过）。
import ast as _ast

_ALLOWED_NODES = (
    _ast.Expression, _ast.BoolOp, _ast.And, _ast.Or, _ast.UnaryOp, _ast.Not,
    _ast.Compare, _ast.Lt, _ast.LtE, _ast.Gt, _ast.GtE, _ast.Eq, _ast.NotEq,
    _ast.Is, _ast.IsNot, _ast.In, _ast.NotIn,
    _ast.Name, _ast.Load, _ast.Constant, _ast.Attribute,
)


def eval_condition(expr: str, scopes: Dict[str, Any]) -> bool:
    """受限表达式求值（AST 白名单，拒绝函数调用/下标等任何执行面）。

    支持两种写法（§10.2 原文使用第二种）：
        steps.order.amount < 100000
        {{ steps.ai_decision.outcome == 'approve_order' }}
    """
    inner = expr.strip()
    m = re.fullmatch(r"\{\{(.+?)\}\}", inner, re.DOTALL)
    if m:
        inner = m.group(1).strip()
    tree = _ast.parse(inner, mode="eval")
    for node in _ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ProcessDefinitionError(
                f"unsafe expression node {type(node).__name__}: {expr!r}")
        if isinstance(node, _ast.Constant) and not isinstance(
                node.value, (int, float, str, bool, type(None))):
            raise ProcessDefinitionError(f"unsafe constant in {expr!r}")
    local = {k: (_NS(v) if isinstance(v, dict) else v) for k, v in scopes.items()}
    try:
        code = compile(tree, "<process_condition>", "eval")
        return bool(eval(code, {"__builtins__": {}}, local))  # noqa: S307
    except Exception:
        return False


StepExecutor = Callable[[str, dict], tuple]  # (name, params) -> (ok, data)


class ProcessRun:
    """一次流程实例的执行轨迹与状态。"""

    def __init__(self, proc: ProcessDef) -> None:
        self.proc = proc
        self.scopes: Dict[str, Any] = {"event": {}, "error": {}}
        self.steps: List[dict] = []
        self.done = False
        self.outcome: Optional[str] = None
        self.current: int = 0
        self.actions_sent = 0

    def summary(self) -> dict:
        return {
            "process_id": self.proc.process_id,
            "done": self.done,
            "outcome": self.outcome,
            "steps": list(self.steps),
            "actions_sent": self.actions_sent,
        }


class ProcessEngine:
    """把 ProcessDef 变成 Decision Engine 侧的行为。

    send_fn: 发送 action 的回调（通常包装 AIPPeer.send_action 并登记关联）。
        返回 (ok, data)——同步内嵌模式下由 driver 阻塞等待 terminal result。
    decision_fn: ai_decision 节点的插槽（C1）：签名 (context, available_actions)
        -> {"outcome": "<choice>", ...}；未提供时该节点产出 uncertain → escalate。
    """

    def __init__(
        self,
        proc: ProcessDef,
        send_fn: StepExecutor,
        *,
        decision_fn: Optional[Callable[[list, list], dict]] = None,
        complete_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.proc = proc
        self.send_fn = send_fn
        self.decision_fn = decision_fn
        self.complete_fn = complete_fn
        self.run = ProcessRun(proc)

    # --- 入口 ---------------------------------------------------------------
    def on_trigger(self, event_name: str, event_data: dict) -> None:
        if self.run.done:
            return
        if self.proc.trigger_name and event_name != self.proc.trigger_name:
            return
        self.run.scopes["event"] = {"name": event_name, "data": event_data or {}}
        self._run_from(0)

    def _run_from(self, index: int) -> None:
        run = self.run
        while index < len(self.proc.steps):
            step = self.proc.steps[index]
            run.current = index
            if step.condition and not eval_condition(step.condition, run.scopes):
                run.steps.append({"step": step.id, "skipped": True})
                index += 1
                continue
            ok = self._exec_step(step)
            if not ok:
                return  # 已跳转 error handler 或终止
            index += 1
        # 全部步骤完成
        run.done = True
        run.outcome = run.outcome or "success"
        if self.complete_fn:
            self.complete_fn(run.outcome)

    def _exec_step(self, step: StepDef) -> bool:
        run = self.run

        # ---- foreach 循环（对标 RF FOR / 影刀循环指令）----
        if step.type == "foreach":
            return self._exec_foreach(step)

        # ---- AI 决策节点 ----
        if step.type == "ai_decision":
            ctx_list = [
                lookup(t, run.scopes)
                for t in step.params.get("context", [])
            ]
            available = step.params.get("available_actions", [])
            if self.decision_fn is None:
                outcome = "uncertain"
            else:
                outcome = self.decision_fn(ctx_list, available).get(
                    "outcome", "uncertain")
            key = step.output_as or step.id
            run.scopes.setdefault("steps", {})[key] = {"outcome": outcome}
            run.steps.append({"step": step.id, "type": "ai_decision",
                              "outcome": outcome})
            if outcome == "uncertain":
                return self._goto_handler(step, reason="ai_uncertain",
                                          default_goto="escalate")
            return True

        params = render(step.params, run.scopes)
        target = render(step.target, run.scopes) if step.target else None
        # 预算守卫：先判断后计数（§10.2 max_actions 必填防无限循环）
        if run.actions_sent + 1 > self.proc.max_actions:
            run.done, run.outcome = True, "max_actions_exceeded"
            return False
        run.actions_sent += 1
        ok, data = self.send_fn(step.action or "", params or {})
        if ok:
            key = step.output_as or step.id
            # context.get 结果解包：{ref, data:{...}} → 直接暴露字段（CoD）
            if (step.action == "context.get" and isinstance(data, dict)
                    and isinstance(data.get("data"), dict)):
                data = data["data"]
            run.scopes.setdefault("steps", {})[key] = data or {}
            run.steps.append({"step": step.id, "action": step.action,
                              "status": "ok"})
            return True
        run.steps.append({"step": step.id, "action": step.action,
                          "status": "failed", "result": data})
        return self._goto_handler(step, reason=(data or {}).get("code", "failed"))

    def _exec_foreach(self, step: StepDef) -> bool:
        """foreach 循环：遍历 source 数组，对每项执行 body_action。

        YAML 示例：
            - id: process_rows
              type: foreach
              params:
                source: "{{steps.extract.rows}}"
                item_var: row
              body_action: erp.order.approve
              body_params:
                order_id: "{{row.order_id}}"
        """
        run = self.run
        items_raw = render(step.params.get("source"), run.scopes)
        if isinstance(items_raw, str):
            try:
                import json as _j
                items_raw = _j.loads(items_raw)
            except (ValueError, TypeError):
                items_raw = []
        if not isinstance(items_raw, list):
            items_raw = [items_raw]

        item_var = step.params.get("item_var", "item")
        body_action = step.params.get("body_action", "")
        body_params_tpl = step.params.get("body_params") or {}

        all_ok = True
        results: List[Dict[str, Any]] = []

        for idx, item in enumerate(items_raw):
            run.scopes[item_var] = item

            body_form = build_process({"process": {
                "id": f"{step.id}_body_{idx}",
                "mode": "process",
                "trigger": {},
                "steps": step.body_steps or (
                    [{"id": "inner", "action": body_action,
                      "params": render(body_params_tpl, run.scopes)}]
                    if body_action else []),
            }})

            sub_engine = ProcessEngine(
                body_form,
                self.send_fn,
                decision_fn=self.decision_fn,
            )
            sub_engine.run.scopes["event"] = run.scopes.get("event", {})
            for k, v in run.scopes.get("steps", {}).items():
                sub_engine.run.scopes.setdefault("steps", {})[k] = v
            sub_engine._run_from(0)

            ok = sub_engine.run.outcome == "success"
            results.append({"index": idx, "ok": ok})
            if not ok:
                all_ok = False

        key = step.output_as or step.id
        run.scopes.setdefault("steps", {})[key] = {"count": len(results)}
        run.steps.append({
            "step": step.id, "type": "foreach",
            "iterations": len(results), "all_ok": all_ok,
        })
        return all_ok

    def _goto_handler(self, step: StepDef, *, reason: str,
                      default_goto: Optional[str] = None) -> bool:
        goto = (step.on_failure or {}).get("goto") or default_goto
        run = self.run
        if not goto:
            run.done, run.outcome = True, "failed"
            if self.complete_fn:
                self.complete_fn("failure")
            return False
        handler = self.proc.error_handlers.get(goto)
        if handler is None:
            run.done, run.outcome = True, "failed"
            if self.complete_fn:
                self.complete_fn("failure")
            return False
        run.scopes.setdefault("error", {})["reason"] = reason
        run.steps.append({"step": step.id, "goto": goto, "reason": reason})
        ok, data = self.send_fn(handler.action or "",
                                render(handler.params, run.scopes) or {})
        run.steps.append({"step": f"{goto}(handler)",
                          "action": handler.action,
                          "status": "ok" if ok else "failed",
                          **({"result": data} if not ok else {})})
        run.done = True
        run.outcome = "escalated" if ok else "failed"
        if self.complete_fn:
            self.complete_fn(run.outcome)
        return False