"""apa-core: 数据抓取向导 —— 结构推断纯函数层（影刀数据抓取向导对标）。

输入：两次点击的 DOM 路径（root→元素，每步 {tag, idx(同标签序号), cls, id}）
输出：行选择器（可泛化到全部兄弟行）与列的相对选择器。

三级策略：
  1. 共享类：两行节点同 tag 且共享 class，父容器内该类节点数≥3
     → `tag.class`
  2. 裸标签：父容器内同 tag 兄弟≥2 → `tag`
  3. 序号兜底：`tag:nth-of-type(k)`（仅首行可用，不泛化时提示）

列路径：自列元素向上爬至行元素，收集 [tag:nth-of-type] 段。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 路径工具
# ---------------------------------------------------------------------------

def _seg_key(seg: Dict[str, Any]) -> str:
    return f"{seg.get('tag', '*')}[{seg.get('idx', 0)}]"


def common_prefix_len(p1: List[Dict], p2: List[Dict]) -> int:
    n = 0
    for a, b in zip(p1, p2):
        if _seg_key(a) != _seg_key(b):
            break
        n += 1
    return n


def _css_seg(seg: Dict[str, Any]) -> str:
    """单个路径段 → CSS 片段（tag + 类名）。"""
    tag = seg.get("tag") or "*"
    cls = (seg.get("cls") or "").strip()
    # 取第一个类名（类名可能带冒号等伪类字符则放弃）
    first_cls = cls.split()[0] if cls else ""
    if first_cls and all(ch.isalnum() or ch in "-_" for ch in first_cls):
        return f"{tag}.{first_cls}"
    return tag


def _path_to_css(path: List[Dict], *, use_nth: bool = True) -> str:
    """root-first 路径 → 绝对 CSS（nth-of-type 锚定）。"""
    parts = []
    for seg in path:
        s = _css_seg(seg)
        if use_nth:
            s += f":nth-of-type({int(seg.get('idx', 0)) + 1})"
        parts.append(s)
    return " > ".join(parts)


def _siblings_with_same_tag(parent_seg_ctx: Dict[str, Any],
                            tag: str) -> int:
    return int(parent_seg_ctx.get("same_tag_siblings", {}).get(tag, 0))


# ---------------------------------------------------------------------------
# 行选择器推断
# ---------------------------------------------------------------------------

def infer_row_selector(
    p1: List[Dict[str, Any]],
    p2: List[Dict[str, Any]],
    *,
    ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """由两行点击路径推断可泛化行选择器。

    ctx 可选字段：repeat_parent = {same_tag_siblings: {tag: count}}
    （由注入脚本在点击时统计父容器内各 tag 的兄弟数量，用于泛化判定）

    返回：
      {selector, strategy: shared_class|bare_tag|nth_fallback,
       repeat_tag, depth_from_root, ok: bool, reason?}
    """
    if not p1 or not p2:
        return {"ok": False, "reason": "empty path",
                "selector": "", "strategy": "", "repeat_tag": ""}

    pref = common_prefix_len(p1, p2)
    if pref == 0:
        return {"ok": False, "reason": "no common ancestor",
                "selector": "", "strategy": "", "repeat_tag": ""}
    if pref >= len(p1) or pref >= len(p2):
        # 一条路径是另一条的前缀：同一元素或父子 → 无法构成"行"
        return {"ok": False, "reason": "nested/same element",
                "selector": "", "strategy": "", "repeat_tag": ""}

    # 重复轴 = 前缀后第一层
    r1, r2 = p1[pref], p2[pref]
    if r1.get("tag") != r2.get("tag"):
        # 不同标签的兄弟（如混排列表）：退化为裸标签不可行，用父级定位
        return {"ok": False, "reason": "different tags at repeat axis",
                "selector": "", "strategy": "", "repeat_tag": r1.get("tag", "")}

    repeat_tag = r1["tag"]
    tail1 = p1[pref:]          # 行内剩余路径（用于列相对定位参考）
    parent_ctx = (ctx or {}).get("repeat_parent") or {}

    # 策略1：共享类
    c1 = (r1.get("cls") or "").split()
    c2 = (r2.get("cls") or "").split()
    shared = [c for c in c1 if c in c2]
    if shared:
        cls = max(shared, key=len)
        if _valid_css_class(cls):
            n_same = _siblings_with_same_tag(parent_ctx, repeat_tag)
            if n_same >= 3 or n_same == 0:  # 无统计信息时乐观采用
                sel_tail = f"{repeat_tag}.{cls}"
                return _finish(p1, pref, sel_tail, "shared_class",
                               repeat_tag)

    # 策略2：裸标签（父容器内该 tag 兄弟 ≥2 即可泛化）
    n_same = _siblings_with_same_tag(parent_ctx, repeat_tag)
    if n_same >= 2 or n_same == 0:
        sel_tail = repeat_tag
        return _finish(p1, pref, sel_tail, "bare_tag", repeat_tag)

    # 策略3：序号兜底
    sel_tail = f"{repeat_tag}:nth-of-type({int(r1.get('idx', 0)) + 1})"
    return _finish(p1, pref, sel_tail, "nth_fallback", repeat_tag)


def _finish(p1, pref, sel_tail, strategy, repeat_tag) -> Dict[str, Any]:
    # 头部锚点精简：html/body 是噪声；取最近一段，优先带类者
    head_segs = [s for s in p1[:pref]
                 if s.get("tag") not in ("html", "body")]
    head = ""
    if head_segs:
        anchor = head_segs[-1]
        s = _css_seg(anchor)
        if "." not in s and len(head_segs) > 1:
            # 锚点无类 → 前一段若有类则拼接，增强唯一定位
            prev = _css_seg(head_segs[-2])
            if "." in prev:
                head = f"{prev} > {s}"
            else:
                head = s
        else:
            head = s
    selector = f"{head} > {sel_tail}" if head else sel_tail
    return {
        "ok": True,
        "selector": selector,
        "strategy": strategy,
        "repeat_tag": repeat_tag,
        "depth_from_root": pref,
    }


def _valid_css_class(cls: str) -> bool:
    return bool(cls) and all(ch.isalnum() or ch in "-_" for ch in cls)


# ---------------------------------------------------------------------------
# 列相对选择器
# ---------------------------------------------------------------------------

def relative_column_path(row_path: List[Dict],
                         col_path: List[Dict]) -> Dict[str, Any]:
    """列元素相对行元素的 CSS 路径。col 必须位于 row 子树内。

    返回 {ok, selector, direct: bool}；direct=True 表示列元素就是行本身
    （整行作为单值抓取）。
    """
    pref = common_prefix_len(row_path, col_path)
    if pref < len(row_path):
        return {"ok": False, "selector": "",
                "reason": "column not inside row subtree"}
    rest = col_path[len(row_path):]
    if not rest:
        return {"ok": True, "selector": ".", "direct": True}
    parts = []
    for seg in rest:
        s = _css_seg(seg)
        parts.append(f"{s}:nth-of-type({int(seg.get('idx', 0)) + 1})")
    return {"ok": True, "selector": " > ".join(parts),
            "direct": False}


# ---------------------------------------------------------------------------
# 步骤生成
# ---------------------------------------------------------------------------

def build_scrape_steps(
    *,
    process_step_base: str,
    url: str,
    row_selector: str,
    columns: Dict[str, str],
    next_selector: Optional[str] = None,
    filter_column: Optional[str] = None,
    filter_value: Any = None,
    body_action: Optional[str] = None,
    body_params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """生成 extract_table (+可选翻页循环) 步骤序列。

    步骤 id 以 base 编号：{base}_open / {base}_scrape / ...
    """
    steps: List[Dict[str, Any]] = [
        {"id": f"{process_step_base}_open",
         "action": "browser.navigate",
         "params": {"url": url}},
        {"id": f"{process_step_base}_scrape",
         "action": "browser.extract_table",
         "params": {
             "row_selector": row_selector,
             "columns": dict(columns),
             "output_context": f"{process_step_base}_data",
         }},
    ]

    if next_selector:
        steps.append({
            "id": f"{process_step_base}_next_hint",
            "action": "browser.click",
            "params": {"target": next_selector},
        })

    if filter_column and filter_value is not None:
        steps.append({
            "id": f"{process_step_base}_filter",
            "action": "data.filter",
            "params": {
                "source": f"{{{{steps.{process_step_base}_scrape.rows}}}}",
                "column": filter_column,
                "op": ">",
                "value": filter_value,
            },
        })

    if body_action:
        steps.append({
            "id": f"{process_step_base}_loop",
            "type": "foreach",
            "params": {
                "source":
                    f"{{{{steps.{process_step_base}_scrape.rows}}}}",
                "item_var": "row",
                "body_action": body_action,
                "body_params": dict(body_params or {}),
            },
        })
    return steps