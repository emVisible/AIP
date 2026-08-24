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


class _LoopBreak(Exception):
    """loop.break 内部信号：最近的循环立即退出（引擎私有，不经协议）。"""


class _LoopContinue(Exception):
    """loop.continue 内部信号：跳过本轮剩余 body。"""




def sub_engine_run_scopes_set(sub_engine, key: str, value) -> None:
    sub_engine.run.scopes[key] = value

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
            body_steps=[to_step(b) for b in (raw.get("body_steps") or [])],
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
    # Phase A：算术（循环条件 n % 2、计数比较等）
    _ast.BinOp, _ast.Add, _ast.Sub, _ast.Mult, _ast.Div, _ast.FloorDiv,
    _ast.Mod, _ast.Pow,
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


def _eval_while_cond(expr: str, scopes: Dict[str, Any]) -> Optional[bool]:
    """while 专用三态求值：True / False / None(求值异常，如首轮键缺失)。

    与 eval_condition 同一 AST 白名单；区别仅在不吞异常。
    """
    inner = expr.strip()
    m = re.fullmatch(r"\{\{(.+?)\}\}", inner, re.DOTALL)
    if m:
        inner = m.group(1).strip()
    try:
        tree = _ast.parse(inner, mode="eval")
        for node in _ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                return None
            if isinstance(node, _ast.Constant) and not isinstance(
                    node.value, (int, float, str, bool, type(None))):
                return None
        local = {k: (_NS(v) if isinstance(v, dict) else v)
                 for k, v in scopes.items()}
        code = compile(tree, "<while_cond>", "eval")
        return bool(eval(code, {"__builtins__": {}}, local))  # noqa: S307
    except Exception:
        return None


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
        process_loader: Optional[Callable[[str], "ProcessDef"]] = None,
        loop_depth: int = 0,
    ) -> None:
        self.proc = proc
        self.send_fn = send_fn
        self.decision_fn = decision_fn
        self.complete_fn = complete_fn
        self.process_loader = process_loader
        # 循环嵌套深度：loop.break/continue 合法性判定（Phase A）
        self.loop_depth = int(loop_depth)
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

        # ---- 循环控制流（Phase A）----
        if step.type in ("loop.break", "loop.continue"):
            if getattr(self, "loop_depth", 0) <= 0:
                raise ProcessDefinitionError(
                    f"{step.id}: {step.type} outside any loop "
                    "(控制流必须位于 foreach/while 循环体内)")
            if step.type == "loop.break":
                raise _LoopBreak()
            raise _LoopContinue()

        # ---- foreach 循环（对标 RF FOR / 影刀循环指令）----
        if step.type == "foreach":
            return self._exec_foreach(step)

        # ---- while 条件循环（M2）----
        if step.type == "while":
            return self._exec_while(step)

        # ---- 日志节点（M2）----
        if step.type == "log":
            msg = render(step.params.get("message", ""), run.scopes)
            run.steps.append({"step": step.id, "type": "log",
                              "message": str(msg)})
            return True

        # ---- 子流程调用 ----
        if step.type == "sub_process":
            return self._exec_sub_process(step)

        # ---- AI 决策节点 ----
        if step.type == "ai_decision":
            # render：整值 {{path}} 保留原生类型；混合串做子串插值
            ctx_list = [
                render(t, run.scopes)
                for t in step.params.get("context", [])
            ]
            available = step.params.get("available_actions", [])
            meta: Dict[str, Any] = {}
            if self.decision_fn is None:
                outcome = "uncertain"
                meta["_reason"] = "no_decision_fn"
            else:
                res = self.decision_fn(ctx_list, available) or {}
                outcome = res.get("outcome", "uncertain")
                meta = {k: v for k, v in res.items() if k.startswith("_")}
                if outcome == "uncertain" and "_reason" not in meta:
                    meta["_reason"] = str(
                        res.get("_reason") or res.get("uncertain") or "?")
            key = step.output_as or step.id
            run.scopes.setdefault("steps", {})[key] = {
                "outcome": outcome,
                **({"_reason": meta["_reason"]} if "_reason" in meta else {}),
            }
            entry = {"step": step.id, "type": "ai_decision",
                     "outcome": outcome}
            if meta:
                entry["meta"] = meta
            run.steps.append(entry)
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

    def _exec_while(self, step: StepDef) -> bool:
        """while 条件循环（M2，影刀「循环-当条件满足」对标）。

        YAML 示例：
            - id: poll
              type: while
              params:
                condition: "steps.poll.last.status != 'done'"   # AST 白名单
                max_iterations: 20                              # 必填守卫
                body_action: api.http.get
                body_params: { url: "https://x/api/status" }
        每轮把 body 结果写入 steps.<output_as>.last 供下一轮条件读取。
        条件表达式键缺失（求值异常）视为 True 进入——轮询型循环的
        「状态未知 ≠ 完成」直觉；显式 False 才退出。
        达到 max_iterations 仍未满足 → 输出 capped=true（整体仍 success，
        防死循环但可被后续条件分支感知）。
        """
        run = self.run
        cond_expr = str(step.params.get("condition", "")).strip()
        try:
            max_iter = int(step.params.get("max_iterations", 0))
        except (TypeError, ValueError):
            max_iter = 0
        if not cond_expr:
            raise ProcessDefinitionError(
                f"{step.id}: while requires 'condition'")
        if max_iter < 1:
            raise ProcessDefinitionError(
                f"{step.id}: while requires max_iterations >= 1 "
                "(死循环守卫，§10.2 精神)")

        body_action = step.params.get("body_action") or ""
        body_steps_spec = (step.body_steps or [])
        body_params_tpl = step.params.get("body_params") or {}
        key_out = step.output_as or step.id
        use_sub = bool(body_steps_spec)   # 子步骤模式：支持 break/continue

        def cond_holds() -> bool:
            """None（求值异常，如首轮无数据）→ 乐观进入。"""
            v = _eval_while_cond(cond_expr, run.scopes)
            return True if v is None else v

        iterations = 0
        capped = True
        broke = False
        last_data: Any = None
        last_ok = True

        while iterations < max_iter:
            # 条件不满足 → 正常退出（求值异常=乐观进入）
            if not cond_holds():
                capped = False
                break

            # 全局预算守卫（§10.2）：条件判断不计动作，body 计
            if body_action and not use_sub:
                if run.actions_sent + 1 > self.proc.max_actions:
                    run.done = True
                    run.outcome = "max_actions_exceeded"
                    return False
                bp = render(body_params_tpl, run.scopes) or {}
                run.actions_sent += 1
                ok, data = self.send_fn(body_action, bp)
                iterations += 1
                last_ok = ok and last_ok
                last_data = data
                run.scopes.setdefault("steps", {})[key_out] = {
                    "iterations": iterations,
                    "last": data,
                    "capped": False,
                }
                if not ok:
                    run.steps.append({
                        "step": step.id, "type": "while",
                        "iterations": iterations,
                        "status": "failed",
                        "result": data})
                    return self._goto_handler(step, reason="while_body_failed")
            elif use_sub:
                if run.actions_sent >= self.proc.max_actions:
                    run.done = True
                    run.outcome = "max_actions_exceeded"
                    return False
                body_form = self._build_loop_body(
                    step, f"it_{iterations}", body_steps_spec, run.scopes)
                sub_engine = ProcessEngine(
                    body_form,
                    self.send_fn,
                    decision_fn=self.decision_fn,
                                loop_depth=self.loop_depth + 1,)
                for k, v in run.scopes.items():
                    if k not in ("steps", "error"):
                        sub_engine_run_scopes_set(sub_engine, k, v)
                sub_engine.run.scopes["event"] = \
                    dict(run.scopes.get("event") or {})
                for k, v in (run.scopes.get("steps") or {}).items():
                    sub_engine.run.scopes.setdefault("steps", {})[k] = v
                try:
                    sub_engine._run_from(0)
                except _LoopBreak:
                    iterations += 1
                    broke = True
                    break
                except _LoopContinue:
                    iterations += 1
                    continue
                run.actions_sent += sub_engine.run.actions_sent
                ok = sub_engine.run.outcome == "success"
                iterations += 1
                last_ok = ok and last_ok
                run.scopes.setdefault("steps", {})[key_out] = {
                    "iterations": iterations, "capped": False}
                if not ok:
                    run.steps.append({
                        "step": step.id, "type": "while",
                        "iterations": iterations, "status": "failed"})
                    return self._goto_handler(
                        step, reason="while_body_failed")
            else:
                iterations += 1  # 无 body：纯条件等待（配合 delay 使用）

        capped = bool(broke is False and iterations >= max_iter
                      and cond_holds())

        out_meta: Dict[str, Any] = {
            "iterations": iterations,
            "capped": capped,
        }
        if last_data is not None:
            out_meta["last"] = last_data
        if broke:
            out_meta["breaked"] = True
        run.scopes.setdefault("steps", {})[key_out] = out_meta
        run.steps.append({"step": step.id, "type": "while",
                          **out_meta})
        return last_ok


    def _build_loop_body(self, step: StepDef, tag: str,
                         steps_spec: List[StepDef],
                         scopes_snapshot_src: Dict[str, Any],
                         ) -> "ProcessDef":
        """构建循环体子 ProcessDef（StepDef 已解析，逐字段渲染模板）。

        预算：max_actions 取父流程剩余额度，执行后由调用方并账。
        错误处理器继承父流程（escalate 等在循环体内同样可达）。
        """
        import dataclasses

        rendered: List[StepDef] = []
        for sd_raw in steps_spec:
            sd = sd_raw if isinstance(sd_raw, StepDef) else StepDef(
                id=str(sd_raw.get("id") or "inner"),
                action=sd_raw.get("action"),
                params=sd_raw.get("params") or {},
                condition=sd_raw.get("condition"),
                output_as=sd_raw.get("output_as"),
            )
            rendered.append(dataclasses.replace(
                sd,
                params=render(sd.params or {}, scopes_snapshot_src),
                target=(render(sd.target, scopes_snapshot_src)
                        if sd.target else None),
            ))
        remaining = max(1, self.proc.max_actions - self.run.actions_sent)
        return dataclasses.replace(
            self.proc,
            process_id=f"{step.id}_{tag}",
            steps=rendered,
            max_actions=remaining,
        )

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

        # Phase A: 字典 → {key, value} 二元组序列（ForEach 字典循环对标）
        if isinstance(items_raw, dict):
            items: List[Any] = [{"key": k, "value": v}
                                 for k, v in items_raw.items()]
        elif isinstance(items_raw, list):
            items = items_raw
        else:
            items = [items_raw]

        item_var = step.params.get("item_var", "item")
        body_action = step.params.get("body_action", "")
        body_params_tpl = step.params.get("body_params") or {}
        body_steps_spec = (step.body_steps or [])
        has_body = bool(body_steps_spec) or bool(body_action)

        all_ok = True
        results: List[Dict[str, Any]] = []
        broke = False

        for idx, item in enumerate(items):
            # 预算穿透（Phase A）：子引擎动作并入全局守卫
            if run.actions_sent >= self.proc.max_actions and has_body:
                run.done = True
                run.outcome = "max_actions_exceeded"
                return False

            run.scopes[item_var] = item

            steps_for_body = body_steps_spec or (
                [{"id": "inner", "action": body_action,
                  "params": render(body_params_tpl, run.scopes)}]
                if body_action else [])

            if not steps_for_body:
                results.append({"index": idx, "ok": True})
                continue
            body_form = self._build_loop_body(
                step, f"body_{idx}", steps_for_body, run.scopes)

            sub_engine = ProcessEngine(
                body_form,
                self.send_fn,
                decision_fn=self.decision_fn,
                        loop_depth=self.loop_depth + 1,)
            # Phase A：顶层作用域整体继承（item_var 等循环变量
            # 必须对子引擎可见），steps/error 由下方专门播种
            for k, v in run.scopes.items():
                if k not in ("steps", "error"):
                    sub_engine_run_scopes_set(sub_engine, k, v)
            sub_engine.run.scopes["event"] = run.scopes.get("event", {})
            for k, v in run.scopes.get("steps", {}).items():
                sub_engine.run.scopes.setdefault("steps", {})[k] = v

            def _absorb_budget() -> bool:
                """子引擎消耗并入全局预算；超限置终态并返回 False。"""
                run.actions_sent += getattr(sub_engine.run,
                                             "actions_sent", 0)
                if run.actions_sent > self.proc.max_actions:
                    run.done = True
                    run.outcome = "max_actions_exceeded"
                    return False
                return True

            try:
                sub_engine._run_from(0)
            except _LoopBreak:
                if not _absorb_budget():
                    return False
                # break：跳出整个循环（本轮视为完成）
                results.append({"index": idx, "ok": True, "breaked": True})
                broke = True
                break
            except _LoopContinue:
                if not _absorb_budget():
                    return False
                results.append({"index": idx, "ok": True,
                                 "continued": True})
                continue

            if not _absorb_budget():
                return False

            ok = sub_engine.run.outcome == "success"
            results.append({"index": idx, "ok": ok})
            if not ok:
                all_ok = False

        key = step.output_as or step.id
        run.scopes.setdefault("steps", {})[key] = {
            "count": len(results), **({"breaked": True} if broke else {})}
        run.steps.append({
            "step": step.id, "type": "foreach",
            "iterations": len(results), "all_ok": all_ok,
        })
        return all_ok

    def _exec_sub_process(self, step: StepDef) -> bool:
        """子流程调用：加载并执行另一个 process.yaml。

        YAML 示例：
            - id: validate
              type: sub_process
              params:
                process_id: order_validation
                input:
                  order_id: "{{event.order_id}}"
        """
        run = self.run
        key = step.output_as or step.id

        if self.process_loader is None:
            run.scopes.setdefault("steps", {})[key] = {
                "outcome": "no_loader"}
            run.steps.append({"step": step.id, "type": "sub_process",
                              "status": "skipped_no_loader"})
            return True

        pid = render(step.params.get("process_id"), run.scopes)
        try:
            sub_form = self.process_loader(pid)
        except Exception as e:
            run.steps.append({"step": step.id, "type": "sub_process",
                              "status": "load_failed", "detail": str(e)})
            return self._goto_handler(step, reason="sub_process_load_failed")

        if sub_form is None:
            run.steps.append({"step": step.id, "type": "sub_process",
                              "status": "not_found", "process_id": pid})
            return self._goto_handler(step, reason="sub_process_not_found")

        input_data = render(step.params.get("input") or {}, run.scopes) or {}

        sub_engine = ProcessEngine(
            sub_form,
            self.send_fn,
            decision_fn=self.decision_fn,
            process_loader=self.process_loader,
        )
        merged_event: Dict[str, Any] = dict(run.scopes.get("event") or {})
        if isinstance(input_data, dict):
            merged_event.update(input_data)
        sub_engine.run.scopes["event"] = merged_event
        for k, v in run.scopes.get("steps", {}).items():
            sub_engine.run.scopes.setdefault("steps", {})[k] = v

        sub_engine._run_from(0)
        outcome = sub_engine.run.outcome or "unknown"
        run.actions_sent += sub_engine.run.actions_sent
        run.scopes.setdefault("steps", {})[key] = {
            "outcome": outcome,
            "steps_log": sub_engine.run.steps,
        }
        run.steps.append({"step": step.id, "type": "sub_process",
                          "process_id": pid, "outcome": outcome})
        if outcome != "success":
            return self._goto_handler(step, reason=f"sub_process_{outcome}")
        return True

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