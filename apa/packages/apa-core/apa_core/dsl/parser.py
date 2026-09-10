"""AFL 解析器：文本 → AST（带行号，错误定位到行）。

语法铁律（v1 冻结）：
  - 一行一步；`#` 整行注释；空行忽略；续行符 `\\`（行尾）。
  - 缩进 4 空格（Tab 直接报错）；块（for/while/handler）用缩进体，
    Python 派，无 end。
  - 步骤 id 用 `@id` 显式声明（省略则编译器按序编号 sN）。
  - 修饰子句固定顺序：kv 参数 → `as` → `when` → `on_fail`。
  - `when` 表达式零发明：原样透传引擎 Python 受限 eval＋`{{}}`。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


class DslError(ValueError):
    """带行号的编译错误。ValueError 子类：RPC 映射为 invalid_params
    而非 internal_error——用户写错了，不是服务器坏了。"""

    def __init__(self, message: str, *, line: int = 0, text: str = ""):
        self.line = line
        self.text = text
        if line:
            super().__init__(f"第{line}行: {message}"
                             + (f"\n  > {text.strip()}" if text else ""))
        else:
            super().__init__(message)


# ---- AST --------------------------------------------------------------------

@dataclass
class Tok:
    """词法单元。text 去引号转义；quoted=整串为一个引用串（title 判定）；
    valquoted=k=\"v\" 形（kv 值保持字符串，不做数值推断）；
    raw=源码片（含引号，when 表达式重组用）。"""
    text: str
    quoted: bool = False
    valquoted: bool = False
    raw: str = ""


@dataclass
class FlowHead:
    id: str
    title: str
    line: int


@dataclass
class ActionStep:
    id: Optional[str]          # None = 编译器编号
    action: str
    title: str                 # 仅视图用，编译丢弃
    params: dict
    output_as: Optional[str]
    condition: Optional[str]
    goto: Optional[str]
    line: int


def _split_trailing_goto(words: List[str], lineno: int,
                         raw: str) -> tuple:
    """块头尾部 `on_fail -> T` 剥离 → (剩余词, goto|None)。
    仅识别未加引号位的字面三元组——调用方保证 words 来自已分词；
    `"on_fail"` 作值用的病态 corner（如源名恰为该串）请改名，文档注明。"""
    if len(words) >= 3 and words[-3] == "on_fail" and words[-2] == "->":
        tgt = words[-1]
        if not _valid_ident(tgt):
            raise DslError(f"跳转目标非法：{tgt!r}", line=lineno, text=raw)
        return words[:-3], tgt
    return words, None


@dataclass
class ForStep:
    id: Optional[str]
    var: str
    source: Any
    output_as: Optional[str]
    goto: Optional[str]
    body: List[Any]
    line: int


@dataclass
class WhileStep:
    id: Optional[str]
    expr: str
    max_iter: int
    output_as: Optional[str]
    goto: Optional[str]
    body: List[Any]
    line: int


@dataclass
class AskStep:
    id: Optional[str]
    prompt: str
    with_refs: List[Any]
    options: List[Any]
    output_as: Optional[str]
    line: int


@dataclass
class RunStep:
    id: Optional[str]
    process_id: str
    input: Any
    output_as: Optional[str]
    line: int


@dataclass
class ScriptStep:
    id: Optional[str]
    lang: str
    timeout: Optional[int]
    nosandbox: bool
    output_as: Optional[str]
    code: str
    line: int


@dataclass
class LogStep:
    id: Optional[str]
    message: str
    output_as: Optional[str]
    condition: Optional[str]
    goto: Optional[str]
    line: int


@dataclass
class BreakStep:
    id: Optional[str]
    condition: Optional[str]
    line: int


@dataclass
class ContinueStep:
    id: Optional[str]
    condition: Optional[str]
    line: int


@dataclass
class RepeatStep:
    id: Optional[str]
    count: Any
    start: Any
    output_as: Optional[str]
    goto: Optional[str]
    body: List[Any]
    line: int


@dataclass
class ForeverStep:
    id: Optional[str]
    max_iter: Optional[int]
    output_as: Optional[str]
    goto: Optional[str]
    body: List[Any]
    line: int


@dataclass
class HandlerDef:
    name: str
    body: List[Any]
    line: int


@dataclass
class Program:
    head: FlowHead
    trigger: dict = field(default_factory=dict)
    max_actions: Optional[int] = None
    timeout_minutes: Optional[int] = None
    steps: List[Any] = field(default_factory=list)
    handlers: List[HandlerDef] = field(default_factory=list)


Step = (ActionStep, ForStep, WhileStep, AskStep, RunStep, ScriptStep,
        LogStep, BreakStep, ContinueStep, RepeatStep, ForeverStep)

_IDENT = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
RESERVED_KEYS = {"expect"}   # 引擎有、v1 未开放：明说，不静默吞


# ---- 行切分 ------------------------------------------------------------------

def _join_continuations(raw_lines: List[str]) -> List[tuple]:
    """续行合并 → [(行号, 逻辑行)]。
    朴素版：行尾 \\ 即续行（文档注明）。"""
    out: List[tuple] = []
    buf = ""
    start = 0
    for i, raw in enumerate(raw_lines, 1):
        line = raw.rstrip("\n")
        if buf:
            line = buf + " " + line.strip()
            buf = ""
        else:
            start = i
        if line.rstrip().endswith("\\"):
            buf = line.rstrip()[:-1]
            continue
        out.append((start, line))
    if buf:
        raise DslError("行尾 \\ 后缺续行", line=start, text=buf)
    return out


def _scan(text: str, line: int, raw: str) -> List[Tok]:
    """切 token：深度 0 空白才切（引号/{{}}/[]/{} 内整体保留）。
    `->` 在深度 0 切为独立 token。"""
    toks: List[Tok] = []
    cur: List[str] = []
    quoted: Optional[str] = None
    # whole：引号开启了整个串；valpending：`k="` 形（值引用候选）；
    # valarmed：候选引用闭合后串即结束 → 值确为引用。
    whole = False
    valpending = False
    valarmed = False
    tok_start: Optional[int] = None
    depth = 0
    i, n = 0, len(text)

    def mark_start(idx: int) -> None:
        nonlocal tok_start
        if tok_start is None and cur == []:
            tok_start = idx

    def flush(end: int) -> None:
        nonlocal cur, whole, valpending, valarmed, tok_start
        if cur or whole or tok_start is not None:
            toks.append(Tok("".join(cur), whole,
                            valarmed and not whole,
                            text[tok_start:end] if tok_start is not None
                            else "".join(cur)))
            cur = []
            whole = valpending = valarmed = False
            tok_start = None

    while i < n:
        c = text[i]
        if quoted:
            mark_start(i)
            if c == "\\" and i + 1 < n and text[i + 1] in ("\\", quoted):
                cur.append(text[i + 1])
                i += 2
                continue
            if c == quoted:
                quoted = None
                if valpending:
                    valarmed = True
                    valpending = False
                i += 1
                continue
            cur.append(c)
            i += 1
            continue
        if c in ("'", '"'):
            if not cur:
                whole = True
            elif "".join(cur).endswith("="):
                valpending = True
            else:
                valarmed = False
                valpending = False
            mark_start(i)
            quoted = c
            i += 1
            continue
        if c in "[{":
            mark_start(i)
            depth += 1
            cur.append(c)
            i += 1
            continue
        if c in "]}":
            mark_start(i)
            depth = max(0, depth - 1)
            cur.append(c)
            i += 1
            continue
        if depth == 0 and c in (" ", "\t"):
            flush(i)
            i += 1
            continue
        if depth == 0 and c == "-" and i + 1 < n and text[i + 1] == ">":
            flush(i)
            toks.append(Tok("->", False, False, "->"))
            i += 2
            continue
        mark_start(i)
        if cur or tok_start is not None:
            # 引用闭合后又添字 → 不再是纯值引用
            if not quoted:
                valarmed = False
        cur.append(c)
        i += 1
    if quoted:
        raise DslError("引号未闭合", line=line, text=raw)
    flush(n)
    return toks


def _parse_value(text: str, quoted: bool, line: int, raw: str) -> Any:
    """标量/列表/字典/引用求值。裸词规则：true/false→bool，数字→数，
    其余按字符串（`target=#submit` 无需引号）。
    quoted=True（k="v" 形）强制字符串，不做数值推断。
    容器内部元素若残留引号（scanner 只在顶层脱引），此处剥一层。"""
    t = text if quoted else text.strip()
    if quoted:
        return t
    if t == "null":
        # YAML 有 null，AFL 也得有——否则 round-trip 丢语义
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        # 容器内部残留引号：JSON 直觉——引号即字符串，不再推断类型
        return t[1:-1]
    if t.startswith("{{") and t.endswith("}}"):
        # 模板引用整体：原样透传引擎渲染（不是字典！）
        return t
    if t in ("true", "false"):
        return t == "true"
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(p.strip(), False, line, raw)
                for p in _split_top(inner, ",")]
    if t.startswith("{") and t.endswith("}"):
        import json
        try:
            return json.loads(t)
        except ValueError:
            pass
        # 宽容字典：JSON 失败时按 AFL 值语法解析（如 {"oid": "{{oid}}"）
        inner = t[1:-1].strip()
        if not inner:
            return {}
        out = {}
        for part in _split_top(inner, ","):
            if ":" not in part:
                raise DslError(f"字典片段缺冒号：{part.strip()!r}",
                               line=line, text=raw)
            k, v = part.split(":", 1)
            k = k.strip()
            if len(k) >= 2 and k[0] == k[-1] and k[0] in ("'", '"'):
                k = k[1:-1]
            out[k] = _parse_value(v.strip(), False, line, raw)
        return out
    return t


def _split_top(s: str, sep: str) -> List[str]:
    """顶层分隔（引号/括号内不切）。"""
    parts, cur = [], []
    q: Optional[str] = None
    depth = 0
    for c in s:
        if q:
            cur.append(c)
            if c == q:
                q = None
            continue
        if c in ("'", '"'):
            q = c
            cur.append(c)
            continue
        if c in "[{":
            depth += 1
            cur.append(c)
            continue
        if c in "]}":
            depth = max(0, depth - 1)
            cur.append(c)
            continue
        if c == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(c)
    parts.append("".join(cur))
    return parts


def _valid_ident(name: str) -> bool:
    return bool(name) and all(c in _IDENT for c in name)


def _is_verb(word: str) -> bool:
    """动词位判定：关键字或带点动作名。"""
    return word in ("for", "while", "ask", "run", "script", "log",
                    "handler", "flow", "on", "break", "continue",
                    "repeat", "forever") or "." in word


def _split_id(words: List[str], lineno: int, raw: str) -> tuple:
    """[@id | id] 动词 … → (id|None, 动词下标)。
    DWIM：首词非动词位、次词是动词位 ⇒ 首词为 id（须合法）。
    `@id` 显式写法并存（同一语义）。"""
    if not words:
        raise DslError("空步骤", line=lineno, text=raw)
    if words[0].startswith("@"):
        node_id = words[0][1:]
        if not _valid_ident(node_id):
            raise DslError("@id 须为字母数字下划线", line=lineno,
                           text=raw)
        return node_id, 1
    if len(words) > 1 and not _is_verb(words[0]) and _is_verb(words[1]):
        if not _valid_ident(words[0]):
            raise DslError(f"步骤 id 非法：{words[0]!r}", line=lineno,
                           text=raw)
        return words[0], 1
    return None, 0


# ---- 解析器 ------------------------------------------------------------------

class _Parser:
    def __init__(self, lines: List[tuple]):
        self.lines = lines       # [(行号, 逻辑行)]
        self.pos = 0

    def parse(self) -> Program:
        head = self._parse_head()
        prog = Program(head=head)
        headers_open = True
        while self.pos < len(self.lines):
            lineno, text = self.lines[self.pos]
            stripped = text.strip()
            if not stripped or stripped.startswith("#"):
                self.pos += 1
                continue
            indent = len(text) - len(text.lstrip(" "))
            if "\t" in text[:indent] or (text[:1] == "\t"):
                raise DslError("禁用 Tab 缩进，用 4 空格", line=lineno,
                               text=text)
            if indent > 0:
                raise DslError("顶层语句不能缩进（for/while/handler 体除外）",
                               line=lineno, text=text)
            if indent % 4 != 0:
                raise DslError("缩进必须为 4 空格倍数", line=lineno,
                               text=text)
            is_block = stripped.endswith(":")
            if is_block:
                fixed = self._strip_script_colon(stripped, lineno, text)
                if fixed is None:
                    headers_open = False
                    self._parse_block(prog, 0)
                    continue
                stripped = fixed
            # 头部声明 vs 步骤：flow/on/max/timeout 关键字优先
            first = stripped.split()[0]
            if first in ("on", "max_actions", "timeout_minutes"):
                if not headers_open:
                    raise DslError("头部声明必须在步骤之前", line=lineno,
                                   text=text)
                self._parse_header(prog, lineno, stripped, text)
                self.pos += 1
                continue
            headers_open = False
            prog.steps.append(self._parse_simple(lineno, stripped, text))
            self.pos += 1
        if not prog.steps:
            raise DslError("流程至少需要一个步骤", line=head.line)
        return prog

    # -- 头 --

    def _parse_head(self) -> FlowHead:
        while self.pos < len(self.lines):
            lineno, text = self.lines[self.pos]
            s = text.strip()
            self.pos += 1
            if not s or s.startswith("#"):
                continue
            toks = _scan(s, lineno, text)
            words = [t.text for t in toks]
            if not words or words[0] != "flow":
                raise DslError("文件必须以 `flow <id> [\"标题\"]` 开头",
                               line=lineno, text=text)
            if len(words) < 2 or not _valid_ident(words[1]):
                raise DslError("flow id 须为字母数字下划线", line=lineno,
                               text=text)
            title = ""
            if len(words) > 2:
                if len(words) > 3 or not toks[2].quoted:
                    raise DslError("标题须为一个带引号字符串", line=lineno,
                                   text=text)
                title = words[2]
            return FlowHead(id=words[1], title=title, line=lineno)
        raise DslError("空文件")

    def _parse_header(self, prog: Program, lineno: int,
                      stripped: str, raw: str) -> None:
        toks = _scan(stripped, lineno, raw)
        words = [t.text for t in toks]
        if words[0] == "on":
            if len(words) == 3 and words[1] == "event":
                prog.trigger = {"type": "event", "name": words[2]}
            elif len(words) == 2 and words[1] == "manual":
                prog.trigger = {}
            else:
                raise DslError("on 写法：`on event <名>` 或 `on manual`",
                               line=lineno, text=raw)
        elif words[0] in ("max_actions", "timeout_minutes"):
            if len(words) != 2 or not words[1].isdigit() \
                    or int(words[1]) < 1:
                raise DslError(f"{words[0]} 后须跟正整数", line=lineno,
                               text=raw)
            setattr(prog, words[0], int(words[1]))

    def _strip_script_colon(self, stripped: str, lineno: int,
                              raw: str) -> Optional[str]:
        """script 头尾随冒号 → 剥掉按独占步解析
        （用户十有八九会写冒号）；id 取裸写/`@`两形（与 _split_id 同口径）。
        非 script 返回 None（走正常块分支，该报错报错）。"""
        body = stripped[:-1].rstrip()
        toks = _scan(body, lineno, raw)
        words = [t.text for t in toks]
        try:
            _, j = _split_id(words, lineno, raw)
        except DslError:
            return None
        if j < len(words) and words[j] == "script":
            return body
        return None

    # -- 块 --

    def _parse_block(self, prog: Program, level: int) -> None:
        node = self._parse_block_node(level)
        if isinstance(node, HandlerDef):
            if level > 0:
                raise DslError("handler 只能在顶层定义", line=node.line)
            prog.handlers.append(node)
            return
        if level > 0:
            raise DslError("内部错误：嵌套块挂载", line=node.line)
        prog.steps.append(node)

    def _parse_block_node(self, level: int) -> Any:
        """块头解析（顶层/嵌套共用）→ HandlerDef 或带空 body 的 for/while。
        body 由调用方经 _collect_body 填充。"""
        lineno, text = self.lines[self.pos]
        stripped = text.strip()[:-1].rstrip()   # 去结尾冒号
        toks = _scan(stripped, lineno, text)
        words = [t.text for t in toks]
        node_id, i = _split_id(words, lineno, text)
        if i >= len(words):
            raise DslError("块头缺关键字", line=lineno, text=text)
        kw = words[i]
        if kw not in ("handler", "for", "while", "repeat", "forever"):
            if kw in ("flow", "on", "ask", "run", "script", "log",
                      "break", "continue"):
                raise DslError(f"{kw} 是独占步/头关键字，不能作块头",
                               line=lineno, text=text)
            raise DslError("块关键字须为 for/while/repeat/forever/handler，"
                           f"得 {kw!r}", line=lineno, text=text)
        # 先验头再收体：坏关键字不应被体错误掩盖；script 等独占步
        # 即使带冒号也不进块分支（由调用方预判）。
        self.pos += 1
        body = self._collect_body(level + 1)
        if kw == "handler":
            rest = words[i + 1:]
            if len(rest) != 1 or not _valid_ident(rest[0]):
                raise DslError("handler 写法：`handler <名>:`", line=lineno,
                               text=text)
            if len(body) != 1:
                raise DslError(
                    f"handler 体必须恰为一个步骤（得 {len(body)} 个）",
                    line=lineno, text=text)
            return HandlerDef(name=rest[0], body=body, line=lineno)
        if kw == "for":
            node = self._parse_for(node_id, words[i + 1:], lineno, text)
        elif kw == "while":
            node = self._parse_while(node_id, words[i + 1:], lineno, text)
        elif kw == "repeat":
            node = self._parse_repeat(node_id, words[i + 1:], lineno, text)
        else:  # forever（上文已验集合）
            node = self._parse_forever(node_id, words[i + 1:], lineno, text)
        node.body = body
        return node

    def _collect_body(self, want_level: int) -> List[Any]:
        """收集缩进体（递归支持嵌套 for/while）。返回 AST 列表。"""
        body: List[Any] = []
        body_start: Optional[int] = None
        while self.pos < len(self.lines):
            lineno, text = self.lines[self.pos]
            stripped = text.strip()
            if not stripped or stripped.startswith("#"):
                self.pos += 1
                continue
            indent = len(text) - len(text.lstrip(" "))
            if indent % 4 != 0:
                raise DslError("缩进必须为 4 空格倍数", line=lineno,
                               text=text)
            if indent // 4 < want_level:
                break
            if indent // 4 > want_level:
                raise DslError("缩进跳层（一次只进一级）", line=lineno,
                               text=text)
            if body_start is None:
                body_start = lineno
            if stripped.endswith(":"):
                fixed = self._strip_script_colon(stripped, lineno, text)
                if fixed is not None:
                    body.append(self._parse_simple(lineno, fixed, fixed))
                    self.pos += 1
                    continue
                # 嵌套块：头解析共用，节点直接挂 body
                node = self._parse_block_node(want_level)
                if isinstance(node, HandlerDef):
                    raise DslError("handler 只能在顶层定义",
                                   line=node.line, text=text)
                body.append(node)
                continue
            body.append(self._parse_simple(lineno, stripped, text))
            self.pos += 1
        if not body:
            raise DslError("块体不能为空", line=body_start or 0)
        return body

    # -- for/while 头 --

    def _parse_for(self, node_id: Optional[str], words: List[str],
                   lineno: int, raw: str) -> ForStep:
        # var in REF [as NAME] [on_fail -> T]
        words, goto = _split_trailing_goto(words, lineno, raw)
        if len(words) < 3 or words[1] != "in":
            raise DslError("for 写法：`for <var> in <ref> [as <名>] [on_fail -> T]:`",
                           line=lineno, text=raw)
        var = words[0]
        if not _valid_ident(var):
            raise DslError("循环变量须为字母数字下划线", line=lineno,
                           text=raw)
        rest = words[2:]
        output_as = None
        if "as" in rest:
            ai = rest.index("as")
            if ai != len(rest) - 2:
                raise DslError("as 在 on_fail 之前：`for x in R as n on_fail -> h:`",
                               line=lineno, text=raw)
            output_as = rest[ai + 1]
            rest = rest[:ai]
        if len(rest) != 1:
            raise DslError("for 源须为单个引用（如 {{event.ids}}）",
                           line=lineno, text=raw)
        return ForStep(id=node_id, var=var, source=rest[0],
                       output_as=output_as, goto=goto, body=[],
                       line=lineno)

    def _parse_repeat(self, node_id: Optional[str], words: List[str],
                      lineno: int, raw: str) -> RepeatStep:
        # repeat <count> [from <start>] [as <var>] [on_fail -> T]
        # (count 可为 {{ref}})
        words, goto = _split_trailing_goto(words, lineno, raw)
        if not words:
            raise DslError("repeat 写法：`repeat <次数> [from <起>] "
                           "[as <var>]:`", line=lineno, text=raw)
        count = _parse_value(words[0], False, lineno, raw)
        rest = words[1:]
        start: Any = 0
        output_as = None
        while rest:
            if rest[0] == "from":
                if len(rest) < 2:
                    raise DslError("from 后缺起始值", line=lineno, text=raw)
                start = _parse_value(rest[1], False, lineno, raw)
                rest = rest[2:]
                continue
            if rest[0] == "as":
                if len(rest) < 2:
                    raise DslError("as 后缺名", line=lineno, text=raw)
                output_as = rest[1]
                rest = rest[2:]
                continue
            raise DslError(f"repeat 行多余片段 {rest[0]!r}", line=lineno,
                           text=raw)
        return RepeatStep(id=node_id, count=count, start=start,
                          output_as=output_as, goto=goto, body=[],
                          line=lineno)

    def _parse_forever(self, node_id: Optional[str], words: List[str],
                       lineno: int, raw: str) -> ForeverStep:
        # forever [max_iter=N] [as <var>] [on_fail -> T]
        words, goto = _split_trailing_goto(words, lineno, raw)
        max_iter = None
        output_as = None
        rest = list(words)
        while rest:
            if rest[0].startswith("max_iter="):
                try:
                    max_iter = int(rest[0].split("=", 1)[1])
                except ValueError:
                    raise DslError("max_iter 须为正整数", line=lineno,
                                   text=raw)
                if max_iter < 1:
                    raise DslError("max_iter 须为正整数", line=lineno,
                                   text=raw)
                rest = rest[1:]
                continue
            if rest[0] == "as":
                if len(rest) < 2:
                    raise DslError("as 后缺名", line=lineno, text=raw)
                output_as = rest[1]
                rest = rest[2:]
                continue
            raise DslError(f"forever 行多余片段 {rest[0]!r}（只要 "
                           f"max_iter/as）", line=lineno, text=raw)
        return ForeverStep(id=node_id, max_iter=max_iter,
                           output_as=output_as, goto=goto, body=[],
                           line=lineno)

    def _parse_while(self, node_id: Optional[str], words: List[str],
                     lineno: int, raw: str) -> WhileStep:
        # EXPR... max_iter=N [as NAME] [on_fail -> T]
        words, goto = _split_trailing_goto(words, lineno, raw)
        mi = [i for i, w in enumerate(words)
              if w.startswith("max_iter=")]
        if len(mi) != 1:
            raise DslError("while 须带 max_iter=N（防死循环，引擎强制）",
                           line=lineno, text=raw)
        mi_idx = mi[0]
        try:
            max_iter = int(words[mi_idx].split("=", 1)[1])
        except ValueError:
            raise DslError("max_iter 须为正整数", line=lineno,
                           text=raw)
        if max_iter < 1:
            raise DslError("max_iter 须为正整数", line=lineno, text=raw)
        expr_toks = words[:mi_idx]
        tail = words[mi_idx + 1:]
        output_as = None
        if tail:
            if len(tail) != 2 or tail[0] != "as":
                raise DslError("while 尾只允许 `as <名>`", line=lineno,
                               text=raw)
            output_as = tail[1]
        if not expr_toks:
            raise DslError("while 缺条件表达式", line=lineno, text=raw)
        return WhileStep(id=node_id, expr=" ".join(expr_toks),
                         max_iter=max_iter, output_as=output_as,
                         goto=goto, body=[], line=lineno)

    # -- 独占步 --

    def _parse_simple(self, lineno: int, stripped: str,
                      raw: str) -> Any:
        if stripped.endswith(":"):
            raise DslError("独占步不能以 : 结尾"
                           "（: 只属于 for/while/repeat/forever/handler）",
                           line=lineno, text=raw)
        toks = _scan(stripped, lineno, raw)
        node_id, i = _split_id([t.text for t in toks], lineno, raw)
        if i >= len(toks):
            raise DslError("空步骤", line=lineno, text=raw)
        verb = toks[i].text
        i += 1
        if verb == "ask":
            return self._parse_ask(node_id, toks, i, lineno, raw)
        if verb == "run":
            return self._parse_run(node_id, toks, i, lineno, raw)
        if verb == "script":
            return self._parse_script(node_id, toks, i, lineno, raw)
        if verb == "log":
            # 消息 = 首个引用串，或修饰子句之前的裸词序列；
            # 其后同样走修饰子句（as/when/on_fail 与动作一致）。
            if i < len(toks) and toks[i].quoted:
                msg = toks[i].text
                i += 1
            else:
                parts = []
                while i < len(toks):
                    w, q = toks[i].text, toks[i].quoted
                    if not q and w in ("as", "when", "on_fail"):
                        break
                    if "=" in w and not q:
                        raise DslError(
                            f"log 行多余片段 {w!r}（log 只取消息＋修饰子句）",
                            line=lineno, text=raw)
                    parts.append(w)
                    i += 1
                msg = " ".join(parts)
                if not msg:
                    raise DslError("log 须带消息：`log \"...\"`",
                                   line=lineno, text=raw)
            output_as, condition, goto, i = self._parse_tail(
                toks, i, lineno, raw, {})
            return LogStep(id=node_id, message=msg, output_as=output_as,
                           condition=condition, goto=goto, line=lineno)
        if verb in ("break", "continue"):
            # 循环控制信号：只取可选 when（取到行尾）；on_fail 无失败语义，
            # 出现即错，不静默吞。
            condition = None
            if i < len(toks):
                w, q = toks[i].text, toks[i].quoted
                if w != "when" or q:
                    raise DslError(
                        f"{verb} 只接受 `when` 修饰，得 {w!r}",
                        line=lineno, text=raw)
                rest = toks[i + 1:]
                if any(t.text == "on_fail" and not t.quoted for t in rest):
                    raise DslError(
                        f"{verb} 不支持 on_fail（控制信号无失败语义）",
                        line=lineno, text=raw)
                condition = " ".join(t.raw for t in rest)
                if not condition:
                    raise DslError("when 后缺表达式", line=lineno,
                                   text=raw)
            cls = BreakStep if verb == "break" else ContinueStep
            return cls(id=node_id, condition=condition, line=lineno)
        if verb in ("for", "while", "repeat", "forever",
                    "handler", "flow", "on"):
            raise DslError(f"{verb} 是块/头关键字，不能作独占步",
                           line=lineno, text=raw)
        if "." not in verb:
            raise DslError(f"动作须写全名（含域，如 browser.click），"
                           f"得 {verb!r}", line=lineno, text=raw)
        # 普通动作：[title] kv* [as] [when] [on_fail]
        title = ""
        if i < len(toks) and toks[i].quoted:
            title = toks[i].text
            i += 1
        params: dict = {}
        output_as, condition, goto, i = self._parse_tail(
            toks, i, lineno, raw, params)
        return ActionStep(id=node_id, action=verb, title=title,
                          params=params, output_as=output_as,
                          condition=condition, goto=goto, line=lineno)

    def _parse_tail(self, toks: List[Tok], i: int, lineno: int,
                    raw: str, params: dict) -> tuple:
        """修饰子句固定顺序：kv 参数 → as → when → on_fail。
        seen 用字符串序比较（"" < "as" < "on_fail" < "when" 恰为合法单调方向），
        失序/重复即报错。返回 (output_as, condition, goto, 新下标)。"""
        output_as = condition = goto = None
        seen = ""
        while i < len(toks):
            w, q = toks[i].text, toks[i].quoted
            if w == "as" and not q:
                if seen >= "as":
                    raise DslError("as 重复", line=lineno, text=raw)
                seen = "as"
                if i + 1 >= len(toks):
                    raise DslError("as 后缺名", line=lineno, text=raw)
                output_as = toks[i + 1].text
                i += 2
                continue
            if w == "when" and not q:
                if seen >= "when":
                    raise DslError("when 重复", line=lineno, text=raw)
                seen = "when"
                try:
                    expr_toks, i2 = self._take_when(toks, i + 1,
                                                   lineno, raw)
                except _GotoCarry as g:
                    # `when EXPR on_fail -> T` 同行：缝合，两字段一次落定
                    condition = g.expr
                    goto = g.goto
                    seen = "on_fail"
                    i = len(toks)
                    continue
                condition = expr_toks
                i = i2
                continue
            if w == "on_fail" and not q:
                seen = "on_fail"
                tgt, i = self._take_goto(toks, i + 1, lineno, raw)
                goto = tgt
                continue
            if seen in ("as", "when", "on_fail"):
                raise DslError("修饰子句顺序：参数 → as → when → on_fail",
                               line=lineno, text=raw)
            if "=" in w and not q:
                k, v = w.split("=", 1)
                if not _valid_ident(k):
                    raise DslError(f"参数名非法：{k!r}", line=lineno,
                                   text=raw)
                if k in RESERVED_KEYS:
                    raise DslError(f"{k} 暂不支持（v1 未开放）", line=lineno,
                                   text=raw)
                params[k] = _parse_value(v, toks[i].valquoted,
                                         lineno, raw)
                i += 1
                continue
            if q:
                raise DslError(f"孤立引号串 {w!r}（title 须紧跟动词）",
                               line=lineno, text=raw)
            # 裸 flag → True（如 clear）
            if not _valid_ident(w):
                raise DslError(f"无法解析的片段 {w!r}", line=lineno,
                               text=raw)
            params[w] = True
            i += 1
        return output_as, condition, goto, i

    def _take_when(self, toks: List[Tok], i: int,
                   lineno: int, raw: str) -> tuple:
        """when 取到行尾，或提前截断于未加引号的 `on_fail -> T`。
        引号内的 on_fail 是字面量，不触发截断。
        表达式按源码片重组（保留引号），不做归一化。"""
        cut = len(toks)
        for j in range(i, len(toks) - 2):
            if toks[j].text == "on_fail" and not toks[j].quoted \
                    and toks[j + 1].text == "->":
                cut = j
                break
        expr = " ".join(t.raw for t in toks[i:cut])
        if not expr:
            raise DslError("when 后缺表达式", line=lineno, text=raw)
        if cut == len(toks) and any(
                t.text == "on_fail" and not t.quoted for t in toks[i:]):
            # 有未加引号的 on_fail 但不成形：不静默吞
            raise DslError("on_fail 写法：`on_fail -> <步骤id|handler|escalate>`",
                           line=lineno, text=raw)
        if cut < len(toks):
            tgt, _ = self._take_goto(toks, cut + 1, lineno, raw)
            raise _GotoCarry(expr, tgt)
        return expr, cut

    def _take_goto(self, toks: List[Tok], i: int,
                   lineno: int, raw: str) -> tuple:
        words = [t.text for t in toks]
        if i + 1 >= len(toks) or words[i] != "->":
            raise DslError("on_fail 写法：`on_fail -> <步骤id|handler|escalate>`",
                           line=lineno, text=raw)
        tgt = words[i + 1]
        if not _valid_ident(tgt):
            raise DslError(f"跳转目标非法：{tgt!r}", line=lineno, text=raw)
        if i + 2 != len(toks):
            raise DslError("on_fail -> T 须在行尾", line=lineno, text=raw)
        return tgt, i + 2

    # -- ask / run / script --

    def _parse_ask(self, node_id: Optional[str], toks: List[Tok], i: int,
                   lineno: int, raw: str) -> AskStep:
        if i >= len(toks) or not toks[i].quoted:
            raise DslError("ask 写法：`ask \"问题\" [with r,..] "
                           "options=[a,b] [as 名]`", line=lineno, text=raw)
        prompt = toks[i].text
        i += 1
        with_refs: List[Any] = []
        options: Optional[List[Any]] = None
        output_as = None
        words = [t.text for t in toks]
        while i < len(toks):
            w = words[i]
            if w == "with":
                i += 1
                while i < len(toks) and words[i] not in ("options", "as") \
                        and not words[i].startswith("options="):
                    with_refs.append(
                        _parse_value(words[i].rstrip(","), False,
                                     lineno, raw))
                    i += 1
                continue
            if w.startswith("options="):
                v = _parse_value(w.split("=", 1)[1], False, lineno, raw)
                if not isinstance(v, list):
                    raise DslError("options 须为列表", line=lineno,
                                   text=raw)
                options = v
                i += 1
                continue
            if w == "as":
                if i + 1 >= len(toks):
                    raise DslError("as 后缺名", line=lineno, text=raw)
                output_as = words[i + 1]
                i += 2
                continue
            raise DslError(f"ask 行多余片段 {w!r}", line=lineno, text=raw)
        if options is None:
            raise DslError("ask 须带 options=[...]", line=lineno, text=raw)
        return AskStep(id=node_id, prompt=prompt, with_refs=with_refs,
                       options=options, output_as=output_as, line=lineno)

    def _parse_run(self, node_id: Optional[str], toks: List[Tok], i: int,
                   lineno: int, raw: str) -> RunStep:
        words = [t.text for t in toks]
        if i >= len(words):
            raise DslError("run 写法：`run <流程id> [in={...}] [as 名]`",
                           line=lineno, text=raw)
        pid = words[i]
        if not _valid_ident(pid):
            raise DslError(f"子流程 id 非法：{pid!r}", line=lineno, text=raw)
        i += 1
        input_v: Any = {}
        output_as = None
        while i < len(toks):
            w = words[i]
            if w.startswith("in="):
                input_v = _parse_value(w.split("=", 1)[1], False,
                                       lineno, raw)
                i += 1
                continue
            if w == "as":
                if i + 1 >= len(toks):
                    raise DslError("as 后缺名", line=lineno, text=raw)
                output_as = words[i + 1]
                i += 2
                continue
            raise DslError(f"run 行多余片段 {w!r}", line=lineno, text=raw)
        return RunStep(id=node_id, process_id=pid, input=input_v,
                       output_as=output_as, line=lineno)

    def _parse_script(self, node_id: Optional[str], toks: List[Tok],
                      i: int, lineno: int, raw: str) -> ScriptStep:
        words = [t.text for t in toks]
        if i >= len(words):
            raise DslError("script 写法：`script python [timeout=N] "
                           "[nosandbox] [as 名]` + 下接 \"\"\" 代码块",
                           line=lineno, text=raw)
        lang = words[i]
        i += 1
        if lang != "python":
            raise DslError(f"v1 仅支持 python（{lang} 预留，未实现）",
                           line=lineno, text=raw)
        timeout = None
        nosandbox = False
        output_as = None
        while i < len(toks):
            w = words[i]
            if w.startswith("timeout="):
                try:
                    timeout = int(w.split("=", 1)[1])
                except ValueError:
                    raise DslError("timeout 须为整数秒", line=lineno,
                                   text=raw)
                if timeout < 1:
                    raise DslError("timeout 须为整数秒", line=lineno,
                                   text=raw)
                i += 1
                continue
            if w == "nosandbox":
                nosandbox = True
                i += 1
                continue
            if w == "as":
                if i + 1 >= len(toks):
                    raise DslError("as 后缺名", line=lineno, text=raw)
                output_as = words[i + 1]
                i += 2
                continue
            raise DslError(f"script 行多余片段 {w!r}", line=lineno,
                           text=raw)
        code = self._take_fence()
        return ScriptStep(id=node_id, lang=lang, timeout=timeout,
                          nosandbox=nosandbox, output_as=output_as,
                          code=code, line=lineno)

    def _take_fence(self) -> str:
        """script 头之后紧跟 \"\"\" 代码块（原文收录，去公共缩进）。
        调用契约：self.pos 仍指着 script 头行。
        结束契约：pos 停在闭合 fence 行，调用方的 +=1 负责消费它
        （与 _parse_simple“不推进 pos”一致，否则 fence 后一行被吞）。"""
        self.pos += 1  # 跨过头行
        n = len(self.lines)
        while self.pos < n:
            lineno, text = self.lines[self.pos]
            s = text.strip()
            if not s or s.startswith("#"):
                self.pos += 1
                continue
            if s != '"""':
                raise DslError("script 头之后须紧跟 \"\"\" 代码块",
                               line=lineno, text=text)
            break
        else:
            raise DslError("script 缺 \"\"\" 代码块")
        self.pos += 1  # 消费 opening fence
        buf: List[tuple] = []
        while self.pos < n:
            lineno, text = self.lines[self.pos]
            if text.strip() == '"""':
                break  # 停在闭合行：调用方推进
            buf.append((lineno, text.rstrip("\n")))
            self.pos += 1
        else:
            raise DslError("代码块缺闭合 \"\"\"")
        # 去公共缩进（空行不参与）
        nonblank = [t for _, t in buf if t.strip()]
        if not nonblank:
            raise DslError("代码块为空")
        indent = min(len(t) - len(t.lstrip(" ")) for t in nonblank)
        return "\n".join(t[indent:] if t.strip() else "" for _, t in buf)


class _GotoCarry(Exception):
    """when 行内提前遇到 on_fail：把 (expr, goto) 带回外层。"""

    def __init__(self, expr: str, goto: str):
        self.expr = expr
        self.goto = goto


def parse_text(src: str) -> Program:
    """AFL 文本 → AST。所有错误都是带行号的 DslError。"""
    raw_lines = src.splitlines()
    # script 代码块内的 # 不是注释：_take_fence 直接消费原行，
    # 此处只做续行合并，不动注释。
    logical = _join_continuations(raw_lines)
    parser = _Parser(logical)
    return parser.parse()
