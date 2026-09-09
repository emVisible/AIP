"""AFL 编译器：AST → process dict（可直接喂 build_process）。

铁律：
  - 引擎零改动：输出 shape 与 YAML loader 一致；验证（重 id/C3）复用
    build_process，不自建第二套。
  - goto 两遍消解：目标须为顶层步骤 id / handler 名 / escalate，
    悬空编译期报错（YAML 只在运行时炸，这是 DSL 的实在改进）。
  - title 是 AFL 层元数据（未来视图用），编译丢弃——StepDef 无此字段。
"""
from __future__ import annotations

from typing import Any, Dict, List, Set

from .parser import (ActionStep, AskStep, DslError, ForStep, HandlerDef,
                     LogStep, Program, RunStep, ScriptStep, WhileStep)


class _Compiler:
    def __init__(self, prog: Program):
        self.prog = prog
        self.auto = 0
        self.seen_ids: Set[str] = set()
        self.goto_targets: Set[str] = {"escalate"}
        self.gotos: List[tuple] = []      # (target, line)

    def compile(self) -> dict:
        # 第一遍：编号＋收集可跳转目标
        for h in self.prog.handlers:
            self._claim(h.name, h.line, what="handler")
            self.goto_targets.add(h.name)
        for s in self.prog.steps:
            self._number(s, top=True)
        for s in self.prog.steps:
            self._collect_goto(s)
        for h in self.prog.handlers:
            for b in h.body:
                self._collect_goto(b)
        # 第二遍：消解
        for tgt, line in self.gotos:
            if tgt not in self.goto_targets:
                raise DslError(
                    f"跳转目标不存在：{tgt!r}（可跳：顶层步骤 id / "
                    f"handler / escalate；循环体内步骤不可被跳入）",
                    line=line)
        proc: Dict[str, Any] = {
            "id": self.prog.head.id,
            "mode": "process",
            "trigger": dict(self.prog.trigger),
            "steps": [self._emit(s) for s in self.prog.steps],
            "error_handlers": {
                h.name: self._emit(h.body[0]) for h in self.prog.handlers
            },
        }
        if self.prog.max_actions is not None:
            proc["max_actions"] = self.prog.max_actions
        if self.prog.timeout_minutes is not None:
            proc["timeout_minutes"] = self.prog.timeout_minutes
        return {"process": proc}

    # -- 第一遍 --

    def _claim(self, name: str, line: int, what: str = "步骤") -> None:
        if name in self.seen_ids:
            raise DslError(f"{what} id 重复：{name!r}", line=line)
        self.seen_ids.add(name)

    def _number(self, node: Any, top: bool) -> None:
        if getattr(node, "id", None):
            kind = "顶层步骤" if top else "嵌套步骤"
            self._claim(node.id, node.line, what=kind)
        else:
            self.auto += 1
            node.id = f"s{self.auto}"
            self._claim(node.id, node.line)
        if top:
            self.goto_targets.add(node.id)
        for b in getattr(node, "body", []) or []:
            self._number(b, top=False)

    def _collect_goto(self, node: Any) -> None:
        g = getattr(node, "goto", None)
        if g:
            self.gotos.append((g, node.line))
        for b in getattr(node, "body", []) or []:
            self._collect_goto(b)

    # -- 第二遍 --

    def _base(self, node: Any) -> Dict[str, Any]:
        d: Dict[str, Any] = {"id": node.id}
        out = getattr(node, "output_as", None)
        if out:
            d["output_as"] = out
        return d

    def _emit(self, node: Any) -> Dict[str, Any]:
        if isinstance(node, ActionStep):
            d = self._base(node)
            d["action"] = node.action
            if node.params:
                d["params"] = node.params
            cond = (node.condition or "").strip()
            if cond:
                d["condition"] = cond
            if node.goto:
                d["on_failure"] = {"goto": node.goto}
            return d
        if isinstance(node, ForStep):
            d = self._base(node)
            d["type"] = "foreach"
            d["params"] = {"source": node.source,
                           "item_var": node.var}
            d["body_steps"] = [self._emit(b) for b in node.body]
            return d
        if isinstance(node, WhileStep):
            d = self._base(node)
            d["type"] = "while"
            d["params"] = {"condition": node.expr,
                           "max_iterations": node.max_iter}
            d["body_steps"] = [self._emit(b) for b in node.body]
            return d
        if isinstance(node, AskStep):
            d = self._base(node)
            d["type"] = "ai_decision"
            # prompt 进 context 首位：引擎只读 context，问题文本不能丢
            d["params"] = {"context": [node.prompt, *node.with_refs],
                           "available_actions": list(node.options)}
            return d
        if isinstance(node, RunStep):
            d = self._base(node)
            d["type"] = "sub_process"
            d["params"] = {"process_id": node.process_id,
                           "input": node.input}
            return d
        if isinstance(node, ScriptStep):
            d = self._base(node)
            d["action"] = "code.python"
            params: Dict[str, Any] = {"code": node.code}
            if node.timeout is not None:
                params["timeout_s"] = node.timeout
            if node.nosandbox:
                params["sandbox"] = False
            d["params"] = params
            return d
        if isinstance(node, LogStep):
            d = self._base(node)
            d["type"] = "log"
            d["params"] = {"message": node.message}
            cond = (node.condition or "").strip()
            if cond:
                d["condition"] = cond
            if node.goto:
                d["on_failure"] = {"goto": node.goto}
            return d
        raise DslError(f"未知节点：{type(node).__name__}")


def compile_text(src: str) -> dict:
    """AFL 文本 → process dict（可直接喂 build_process 做全量校验）."""
    from .parser import parse_text
    return _Compiler(parse_text(src)).compile()


def load_afl(path: str) -> Any:
    """读 .afl 文件 → ProcessDef（经 build_process，复用引擎校验）。"""
    from pathlib import Path

    from apa_core.process import build_process
    data = compile_text(Path(path).read_text(encoding="utf-8"))
    return build_process(data)
