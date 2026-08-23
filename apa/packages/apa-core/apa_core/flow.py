"""apa-core: .flow 文本格式编译器（借鉴 TagUI 动词句 + RF 关键字驱动）。

每行 = 一个动作 + 空格分隔的 key=value 参数。
支持 if/unless 条件、→ output_as、on_failure goto、handler 定义。

示例：
    trigger erp.order.approval_requested

    context.get ref={{context}} fields=[order_id,amount] → order

    erp.order.approve order_id={{order.order_id}} if order.amount < 100000

    handler escalate
      human.task.create task_type=exception
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


class FlowError(ValueError):
    pass


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    # 剥离匹配的包裹引号
    if len(raw) >= 2 and ((raw[0] == raw[-1] == '"') or (raw[0] == raw[-1] == "'")):
        raw = raw[1:-1]
    try:
        import json
        return json.loads(raw)
    except (ValueError, TypeError):
        pass
    return raw


def _shlex_split(text: str) -> List[str]:
    """空格分词但尊重引号。"""
    tokens: List[str] = []
    current: List[str] = []
    in_quote: Optional[str] = None
    for ch in text:
        if in_quote:
            current.append(ch)
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
            current.append(ch)
        elif ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _extract_params(tokens: List[str]) -> Dict[str, Any]:
    """从 token 列表提取 key=value 对。"""
    params: Dict[str, Any] = {}
    for tok in tokens:
        if "=" not in tok:
            continue
        key, _, val = tok.partition("=")
        key = key.strip()
        if not key:
            continue
        params[key] = _parse_value(val.strip())
    return params


def _strip_params_from_line(line: str) -> Tuple[str, Dict[str, Any]]:
    """从行中移除所有 key=value 参数对，返回 (clean_action_part, params)。"""
    tokens = _shlex_split(line)
    action_tokens: List[str] = []
    params: Dict[str, Any] = {}

    for tok in tokens:
        eq = tok.find("=")
        if eq > 0 and not tok[eq-1:eq].isspace() and re.match(r"^[a-zA-Z_]\w*$", tok[:eq]):
            params[tok[:eq]] = _parse_value(tok[eq+1:])
        else:
            action_tokens.append(tok)

    return " ".join(action_tokens), params


# ---- 解析 .flow → 结构 ----
def parse_flow(text: str) -> dict:
    proc: Dict[str, Any] = {
        "id": "", "mode": "process",
        "trigger": {}, "steps": [], "error_handlers": {},
    }
    current_handler: Optional[str] = None
    step_count = 0

    for lineno, raw in enumerate(text.split("\n"), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indented = bool(re.match(r"^\s{2,}", raw))

        # 分离首词和剩余
        space_idx = stripped.find(" ")
        verb = stripped[:space_idx] if space_idx > 0 else stripped
        rest = stripped[space_idx+1:].strip() if space_idx > 0 else ""

        # 指令关键字
        if verb == "trigger":
            proc["trigger"] = {"type": "event", "name": rest}
            continue
        if verb == "max_actions":
            proc["max_actions"] = int(rest) if rest.isdigit() else 50
            continue
        if verb == "id":
            proc["id"] = rest
            continue
        if verb == "id":
            proc["id"] = rest
            continue
        if verb == "handler":
            current_handler = rest
            proc["error_handlers"][rest] = {
                "id": f"handler_{rest}", "action": "", "params": {},
            }
            continue

        # 错误处理器内的动作行
        if indented and current_handler:
            h = proc["error_handlers"][current_handler]
            if not h.get("action"):
                h["action"] = verb
                h["params"] = _extract_params(
                    [t for t in _shlex_split(rest)])
            continue

        # 正常步骤行：verb = action_name [params...] [modifiers...]
        step: Dict[str, Any] = {"id": f"step_{step_count + 1}"}

        clean = stripped

        # 提取 → output_as
        arrow_pos = clean.find("→")
        if arrow_pos >= 0:
            step["output_as"] = clean[arrow_pos+1:].strip()
            clean = clean[:arrow_pos].strip()

        # 提取 on_failure goto X
        fail_match = re.search(r"\bon_failure\s+goto\s+(\S+)", clean)
        if fail_match:
            step["on_failure"] = {"goto": fail_match.group(1)}
            clean = clean[:fail_match.start()].strip()

        # 提取 if/unless 条件
        cond = None
        cond_m = re.search(r"\bif\s+(.+?)\s*$", clean)
        unless_m = re.search(r"\bunless\s+(.+?)\s*$", clean)
        if cond_m:
            cond = cond_m.group(1).strip()
            clean = clean[:cond_m.start()].strip()
        elif unless_m:
            cond = f"not ({unless_m.group(1).strip()})"
            clean = clean[:unless_m.start()].strip()

        # 首词为动作名，其余为参数
        tokens = _shlex_split(clean)
        if not tokens:
            raise FlowError(f"line {lineno}: empty step")
        action = tokens[0]
        param_tokens = tokens[1:]
        params = _extract_params(param_tokens)

        # C3 校验
        bad = {"idempotency", "risk"} & set(params.keys())
        if bad:
            raise FlowError(
                f"line {lineno}: carries {sorted(bad)} — "
                "declare in Action Registry instead (C3)")

        step["action"] = action
        if params:
            step["params"] = params
        if cond:
            step["condition"] = cond
        if step.get("output_as"):
            pass

        proc["steps"].append(step)
        step_count += 1

    if not proc["id"]:
        proc["id"] = "unnamed_flow"

    return proc


# ---- 反编译：结构化流程 → .flow 文本 ----
def decompile_flow(proc_dict: dict) -> str:
    p = proc_dict.get("process", proc_dict)

    def fmt_val(v: Any) -> str:
        if isinstance(v, str):
            if " " in v or "{{" in v or any(c in v for c in ":{}[]"):
                escaped = v.replace("'", "\\'")
                return f"'{escaped}'"
            return v
        import json as _j
        return _j.dumps(v, ensure_ascii=False)

    def fmt_params(params: Optional[dict]) -> str:
        if not params:
            return ""
        return " ".join(f"{k}={fmt_val(v)}" for k, v in params.items())

    lines: List[str] = []

    trigger = p.get("trigger", {})
    if isinstance(trigger, dict) and trigger.get("name"):
        lines.append(f"trigger {trigger['name']}")
    elif isinstance(trigger, str) and trigger:
        lines.append(f"trigger {trigger}")

    if p.get("max_actions") and p["max_actions"] != 100:
        lines.append(f"max_actions {p['max_actions']}")
    lines.append("")

    for s in p.get("steps", []):
        parts: List[str] = [s.get("action", "")]
        target = s.get("target")
        if target:
            parts.append(target)
        params = s.get("params")
        if params:
            pp = fmt_params(params)
            if pp:
                parts.append(pp)
        condition = s.get("condition")
        if condition:
            inner = condition.strip()
            if inner.startswith("{{") and inner.endswith("}}"):
                inner = inner[2:-2].strip()
            parts.insert(0, f"if {inner}")
        lines.append(" ".join(parts))

    handlers = p.get("error_handlers", {})
    if handlers:
        lines.append("")
        for key, h in handlers.items():
            lines.append(f"handler {key}")
            action = h.get("action", "")
            params = h.get("params") or {}
            param_str = fmt_params(params)
            if action:
                lines.append(f"  {action} {param_str}".rstrip())

    return "\n".join(lines) + "\n"


# ---- 双向验证 ----
def roundtrip_check(flow_text: str, process_dict: dict) -> List[str]:
    decompiled = decompile_flow(process_dict)
    recompiled = parse_flow(decompiled)
    errors: List[str] = []

    orig_steps = process_dict.get("process", process_dict).get("steps", [])
    new_steps = recompiled.get("steps", [])

    if len(orig_steps) != len(new_steps):
        errors.append(f"step count mismatch: {len(orig_steps)} vs {len(new_steps)}")

    for i, (o, n) in enumerate(zip(orig_steps, new_steps)):
        if o.get("action") != n.get("action"):
            errors.append(f"step {i}: action mismatch "
                          f"'{o.get('action')}' vs '{n.get('action')}'")

    return errors