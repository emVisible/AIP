"""AFL 打印机：process-dict → 规范 .afl 文本（D1 融合地基）。

输入 shape＝compiler 输出 shape（＝build_process 输入 shape），
即 {"process": {...}} 或裸 process  dict。用途：
  · 画布编辑 → 回写 AFL 文本（显式“从画布更新”，见 D2）
  · YAML 存量 → AFL 迁移（老式 body_action 自动升级为 body_steps）

诚实清单（宁可报错不丢语义）：
  · title 不在 dict 里 → 不打印（注释提醒一句，不伪造）
  · 未知 type → DslError（静默丢 type 等于改语义）
  · 老式 body_action（无 body_steps）→ 就地升级为单步 body（等价，引擎同路径）
  · for_times 缺 count / sub_process 缺 process_id → DslError
  · 空流程 → DslError
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .parser import DslError

_IND = "    "
_BARE_OK = re.compile(r"^[A-Za-z0-9_\-#./:@{}]+$")
_NEEDS_QUOTE_HINT = ("->",)


def _q(s: str) -> str:
    """标量转 AFL 字面量。含空格/引号/括号/等号/`->`/行尾冒号则加引号。"""
    if s == "":
        return '""'
    if (
        _BARE_OK.match(s)
        and not any(h in s for h in _NEEDS_QUOTE_HINT)
        and not s.endswith(":")
    ):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _v(v: Any) -> str:
    """值 → AFL 字面量。None→null；dict→JSON（重解析走宽容分支）。"""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return _q(v)
    if isinstance(v, list):
        return "[" + ", ".join(_v(x) for x in v) + "]"
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return _q(str(v))


def _mods(d: Dict[str, Any]) -> str:
    """as/when/on_fail 修饰尾（固定顺序）。"""
    out = ""
    if d.get("output_as"):
        out += f" as {d['output_as']}"
    cond = (d.get("condition") or "").strip()
    if cond:
        out += f" when {cond}"
    goto = (d.get("on_failure") or {}).get("goto")
    if goto:
        out += f" on_fail -> {goto}"
    return out


def _upgrade_legacy_body(typ: str, params: Dict[str, Any],
                         sid: str) -> List[Dict[str, Any]]:
    """老式 body_action/body_params → 单步 body_steps（语义等价升级）。"""
    act = params.get("body_action") or ""
    if not act:
        return []
    bp = params.get("body_params") or {}
    if not isinstance(bp, dict):
        bp = {}
    return [{"id": f"{sid}_body", "action": act, "params": dict(bp)}]


def _steps(lines: List[str], steps: List[Dict[str, Any]], level: int) -> None:
    for s in steps:
        _step(lines, s, level)


def _step(lines: List[str], s: Dict[str, Any], level: int) -> None:
    p = s.get("params") or {}
    typ = s.get("type") or ""
    pre = _IND * level + s.get("id", "")
    mods = _mods(s)

    def body(dst_level: int, nested: List[Dict[str, Any]]) -> None:
        if not nested:
            raise DslError(f"循环体不能为空：{s.get('id', '?')}")
        _steps(lines, nested, dst_level)

    if typ == "foreach":
        src = _v(p.get("source", ""))
        var = p.get("item_var", "item")
        lines.append(f"{pre} for {var} in {src}"
                     f"{' as ' + s['output_as'] if s.get('output_as') else ''}:")
        nested = s.get("body_steps") or []
        if not nested:
            nested = _upgrade_legacy_body(typ, p, s.get("id", "s"))
        body(level + 1, nested)
        return
    if typ == "while":
        cond = str(p.get("condition", "")).strip()
        mi = p.get("max_iterations")
        if mi is None:
            raise DslError(f"while 缺 max_iterations：{s.get('id', '?')} "
                           f"（引擎强制，打印机不编造）")
        lines.append(f"{pre} while {cond} max_iter={mi}"
                     f"{' as ' + s['output_as'] if s.get('output_as') else ''}:")
        nested = s.get("body_steps") or []
        if not nested:
            nested = _upgrade_legacy_body(typ, p, s.get("id", "s"))
        body(level + 1, nested)
        return
    if typ == "for_times":
        count = p.get("count")
        if count is None:
            raise DslError(f"for_times 缺 count：{s.get('id', '?')}")
        line = f"{pre} repeat {_v(count)}"
        if p.get("start") not in (None, 0):
            line += f" from {_v(p['start'])}"
        var = p.get("item_var")
        if var:
            line += f" as {var}"
        elif s.get("output_as"):
            line += f" as {s['output_as']}"
        lines.append(line + ":")
        nested = s.get("body_steps") or []
        if not nested:
            nested = _upgrade_legacy_body(typ, p, s.get("id", "s"))
        body(level + 1, nested)
        return
    if typ == "loop.infinite":
        line = f"{pre} forever"
        if p.get("max_iterations") is not None:
            line += f" max_iter={p['max_iterations']}"
        if s.get("output_as"):
            line += f" as {s['output_as']}"
        lines.append(line + ":")
        body(level + 1, s.get("body_steps") or [])
        return
    if typ == "ai_decision":
        ctx = p.get("context") or []
        if not ctx:
            raise DslError(f"ask 缺 context（问题文本）:{s.get('id', '?')}")
        # prompt 恒加引号：问题文本天然是句子，裸写必有空格
        line = f"{pre} ask {_q(str(ctx[0]))}"
        if len(ctx) > 1:
            line += " with " + ", ".join(
                _v(x) if not isinstance(x, str) or " " in x or not x
                else x for x in ctx[1:])
        line += f" options={_v(p.get('available_actions', []))}"
        if s.get("output_as"):
            line += f" as {s['output_as']}"
        lines.append(line)
        return
    if typ == "sub_process":
        pid = p.get("process_id")
        if not pid:
            raise DslError(f"sub_process 缺 process_id：{s.get('id', '?')}")
        line = f"{pre} run {pid}"
        if p.get("input"):
            line += f" in={_v(p['input'])}"
        if s.get("output_as"):
            line += f" as {s['output_as']}"
        lines.append(line)
        return
    if typ == "log":
        line = f"{pre} log {_q(str(p.get('message', '')))}" + mods
        lines.append(line)
        return
    if typ in ("loop.break", "loop.continue"):
        kw = "break" if typ == "loop.break" else "continue"
        cond = (s.get("condition") or "").strip()
        lines.append(f"{pre} {kw}" + (f" when {cond}" if cond else ""))
        return
    if typ:
        raise DslError(f"printer 未知类型 {typ!r}（步骤 {s.get('id', '?')}）："
                       f"手动迁移，不静默丢 type")
    # 普通动作
    action = s.get("action") or ""
    if not action:
        raise DslError(f"步骤 {s.get('id', '?')} 无 action 又无 type")
    if action == "code.python" and isinstance(p.get("code"), str) and \
            set(p) <= {"code", "timeout_s", "sandbox"}:
        # 脚本糖：多行代码块可读性碾压单行 kv
        line = f"{pre} script python"
        if p.get("timeout_s") is not None:
            line += f" timeout={p['timeout_s']}"
        if p.get("sandbox") is False:
            line += " nosandbox"
        if s.get("output_as"):
            line += f" as {s['output_as']}"
        lines.append(line + ":")
        lines.append(_IND * (level + 1) + '"""')
        for cl in str(p["code"]).splitlines() or [""]:
            lines.append(_IND * (level + 1) + cl if cl.strip() else "")
        lines.append(_IND * (level + 1) + '"""')
        return
    parts = [f"{pre} {action}"]
    if s.get("target"):
        parts.append(f"target={_v(s['target'])}")
    for k in sorted(p):
        parts.append(f"{k}={_v(p[k])}")
    lines.append(" ".join(parts) + mods)


def print_text(data: dict) -> str:
    """process-dict → 规范 .afl 文本。"""
    proc = data.get("process", data)
    if not isinstance(proc, dict) or not proc.get("id"):
        raise DslError("printer 输入须为 process dict（含 id）")
    lines = [f"flow {proc['id']}"]
    trig = proc.get("trigger") or {}
    if trig.get("type") == "event" and trig.get("name"):
        lines.append(f"on event {trig['name']}")
    else:
        lines.append("on manual")
    # 头默认值恒显式（compiler 同值落盘）：文本即运行真相
    lines.append(f"max_actions {proc.get('max_actions', 100)}")
    lines.append(f"timeout_minutes {proc.get('timeout_minutes', 60)}")
    lines.append("")
    steps = proc.get("steps") or []
    if not steps:
        raise DslError("空流程无可打印")
    _steps(lines, steps, 0)
    handlers = proc.get("error_handlers") or {}
    if handlers:
        lines.append("")
        for name, h in handlers.items():
            lines.append(f"handler {name}:")
            _step(lines, h, 1)
    return "\n".join(lines) + "\n"
