"""AFL 打印机：process-dict → .afl 文本（D1-T3）。

输入 shape＝编译器输出 shape（build_process 输入形），于是
AFL→dict→AFL round-trip 可测。输出为 canonical 形式（稳定、可 diff）。

诚实清单（有损/受限处绝不静默）：
  - title：dict 里没有 → 不打出（AFL→画布→AFL 会丢标题/注释，属已知；
    D2 前端以显式同步按钮＋提示处理，不搞静默覆盖）。
  - 未知 type → DslError 大声报错，不丢语义。
  - 引擎缺省显式化：foreach 缺 item_var 打 `item`；while 缺 condition
    打 `True`（行为一致，文本更直白）。
  - id 非法字符（空格等）→ 报错，引擎侧虽能存但 AFL 写不出。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .parser import DslError, _valid_ident

_IND = "    "
_RESERVED_BARE = {"true", "false", "null", "as", "when", "on_fail"}
_SPECIAL_CHARS = set(',[]{}"\'=\\')


def _needs_quote(s: str) -> bool:
    if not s:
        return True
    if s in _RESERVED_BARE:
        return True
    if "->" in s or s.endswith(":"):
        return True
    if any(c.isspace() for c in s):
        return True
    if any(c in _SPECIAL_CHARS for c in s):
        return True
    try:
        int(s)
        return True
    except ValueError:
        pass
    try:
        float(s)
        return True
    except ValueError:
        pass
    return False


def _val(v: Any) -> str:
    """Python 值 → AFL 值语法。"""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        if "\n" in v:
            raise DslError(
                f"printer：多行字符串写不出单行 kv（{v[:30]!r}…），"
                f"请改用 script 块或附件")
        if re.fullmatch(r"\{\{.*\}\}", v):
            return v  # 纯模板引用裸写：for 源等高频位可读性
        return f'"{v}"' if _needs_quote(v) else v
    if isinstance(v, list):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return f'"{str(v)}"'


def _modifiers(step: Dict[str, Any]) -> str:
    """as / when / on_fail 后缀（固定顺序，与 parser 同构）。"""
    out = ""
    if step.get("output_as"):
        out += f" as {step['output_as']}"
    cond = (step.get("condition") or "").strip()
    if cond:
        out += f" when {cond}"
    goto = (step.get("on_failure") or {}).get("goto")
    if goto:
        out += f" on_fail -> {goto}"
    return out


def _check_id(sid: Any, where: str) -> str:
    s = str(sid or "")
    if not _valid_ident(s):
        raise DslError(f"printer：步骤 id 写不出 AFL：{s!r}（{where}）")
    return s


def _emit_step(step: Dict[str, Any], level: int) -> List[str]:
    p = step.get("params") or {}
    pad = _IND * level
    sid = _check_id(step.get("id"), "顶层" if level == 0 else "循环体")
    typ = step.get("type") or ""
    mod = _modifiers(step)

    def body() -> List[str]:
        subs = step.get("body_steps") or []
        if not subs and p.get("body_action"):
            #  legacy 升级：老式 body_action/body_params 提升为现代体内步；
            #  id 派生确定（`{sid}_body`），params 原样搬运。
            subs = [{"id": f"{sid}_body", "action": p["body_action"],
                     "params": p.get("body_params") or {}}]
        if not subs:
            raise DslError(f"printer：循环体为空：{sid}")
        return [ln for b in subs for ln in _emit_step(b, level + 1)]

    if typ == "foreach":
        var = p.get("item_var", "item")
        lines = [f"{pad}{sid} for {var} in {_val(p.get('source'))}"
                 f"{mod}:"]
        return lines + body()
    if typ == "while":
        cond = str(p.get("condition") or "True")
        mi = p.get("max_iterations")
        if mi is None:
            raise DslError(f"printer：while 缺 max_iterations：{sid}")
        lines = [f"{pad}{sid} while {cond} max_iter={mi}{mod}:"]
        return lines + body()
    if typ == "for_times":
        count = p.get("count")
        if count is None:
            raise DslError(f"printer：for_times 缺 count：{sid}")
        head = f"{pad}{sid} repeat {_val(count)}"
        if p.get("start", 0):
            head += f" from {_val(p['start'])}"
        ivar, oas = p.get("item_var"), step.get("output_as")
        if ivar and oas and ivar != oas:
            raise DslError(
                f"printer：repeat 的 item_var 与 output_as 打架 "
                f"({ivar!r} vs {oas!r})：{sid}，手动二选一")
        var = ivar or oas
        if var:
            head += f" as {var}"
        # as 已落定：mod 去掉 as 避免 `as x as x`（重解析取末者，虽收敛但丑）
        return [head + _modifiers({**step, "output_as": None}) + ":"] + body()
    if typ == "loop.infinite":
        head = f"{pad}{sid} forever"
        if p.get("max_iterations") is not None:
            head += f" max_iter={p['max_iterations']}"
        if step.get("output_as"):
            head += f" as {step['output_as']}"
        return [head + _modifiers({**step, "output_as": None}) + ":"] + body()
    if typ == "loop.break":
        return [f"{pad}{sid} break" + (f" when {step['condition']}"
                if (step.get("condition") or "").strip() else "")]
    if typ == "loop.continue":
        return [f"{pad}{sid} continue" + (f" when {step['condition']}"
                if (step.get("condition") or "").strip() else "")]
    if typ == "ai_decision":
        ctx = list(p.get("context") or [])
        if not ctx:
            raise DslError(f"printer：ai_decision 缺 context：{sid}")
        prompt, rest = ctx[0], ctx[1:]
        if not isinstance(prompt, str):
            raise DslError(f"printer：ai_decision 首 context 须为问题文本："
                           f"{sid}")
        head = f'{pad}{sid} ask "{prompt}"'
        if rest:
            head += " with " + ", ".join(_val(r) for r in rest)
        head += f" options={_val(list(p.get('available_actions') or []))}"
        return [head + mod]
    if typ == "sub_process":
        head = f"{pad}{sid} run {p.get('process_id', '')}"
        if p.get("input"):
            head += f" in={_val(p['input'])}"
        return [head + mod]
    if typ == "log":
        return [f'{pad}{sid} log "{p.get("message", "")}"' + mod]
    if typ:
        raise DslError(f"printer：未知类型 {typ!r}（{sid}），手动迁移")
    # 普通动作；code.python 多行 code 走 script 块
    action = step.get("action") or ""
    if not action or "." not in action:
        raise DslError(f"printer：动作名非法：{action!r}（{sid}）")
    if action == "code.python" and isinstance(p.get("code"), str):
        head = f"{pad}{sid} script python"
        if p.get("timeout_s") is not None:
            head += f" timeout={p['timeout_s']}"
        if p.get("sandbox") is False:
            head += " nosandbox"
        if step.get("output_as"):
            head += f" as {step['output_as']}"
        lines = [head + ":"]
        lines.append(f"{pad}{_IND}\"\"\"")
        for cl in str(p["code"]).splitlines() or [""]:
            lines.append(f"{pad}{_IND}{cl}" if cl.strip() else "")
        lines.append(f"{pad}{_IND}\"\"\"")
        return lines
    parts = [f"{pad}{sid} {action}"]
    if step.get("target"):
        parts.append(f"target={_val(step['target'])}")
    for k in sorted(p.keys()):
        parts.append(f"{k}={_val(p[k])}")
    return [" ".join(parts) + mod]


def print_text(data: dict) -> str:
    """process-dict → .afl 文本。data 形如 {"process": {...}}。"""
    proc = data.get("process") if isinstance(data, dict) else None
    if not isinstance(proc, dict) or not proc.get("id"):
        raise DslError("printer：缺 process.id")
    out = [f"flow {proc['id']}"]
    trig = proc.get("trigger") or {}
    if trig.get("name"):
        out.append(f"on event {trig['name']}")
    else:
        out.append("on manual")
    if proc.get("max_actions") not in (None, 100):
        out.append(f"max_actions {proc['max_actions']}")
    if proc.get("timeout_minutes") not in (None, 60):
        out.append(f"timeout_minutes {proc['timeout_minutes']}")
    out.append("")
    for s in proc.get("steps") or []:
        out.extend(_emit_step(s, 0))
        out.append("")
    for name, h in (proc.get("error_handlers") or {}).items():
        out.append(f"handler {name}:")
        out.extend(_emit_step(h, 1))
        out.append("")
    return "\n".join(out).rstrip() + "\n"
