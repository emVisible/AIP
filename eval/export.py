"""标签沉淀：审计 + 人工决议 → samples jsonl（飞轮起点）。

    python3 -m eval.export --out eval/samples.jsonl
    python3 -m eval.export --data /path/to/data --out /tmp/s.jsonl

标签推导（resolve 即标注，免费标签）：
  自动通过/驳回（via==auto）→ expected=approve/reject
  人工决议（resolved_outcome）→ expected=approve/reject
  pending（未决议）→ 跳过，无标签不配拟合
meta 透传但过凭据过滤（含密码/token 等 key 直接丢弃，C4）。
输出行：{kind,title,body,expected}（category 真值暂空，人工补 labels.category）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CRED_KEY = re.compile(r"(password|passwd|pwd|api[_-]?key|secret|token|身份证|银行卡)",
                       re.IGNORECASE)


def clean_meta(meta: dict) -> dict:
    if not isinstance(meta, dict):
        return {}
    return {k: v for k, v in meta.items()
            if not _CRED_KEY.search(str(k)) and not _CRED_KEY.search(str(v))}


def export_samples(data_dir: str) -> tuple[list, dict]:
    path = os.path.join(data_dir, "reviews.json")
    try:
        with open(path, encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return [], {"pending": 0, "exported": 0}
    rows, pending = [], 0
    for rec in db.values():
        item = rec.get("item", {})
        state = rec.get("state", "")
        if state == "pending":
            pending += 1
            continue
        if state == "approved":
            expected = "approve"
        elif state == "rejected":
            expected = "reject"
        else:
            continue
        rows.append({"kind": item.get("kind", "other"),
                     "title": item.get("title", ""),
                     "body": item.get("body", ""),
                     "expected": expected,
                     "meta": clean_meta(item.get("meta") or {})})
    return rows, {"pending": pending, "exported": len(rows)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data")
    p.add_argument("--out", default="eval/samples.jsonl")
    a = p.parse_args()
    rows, info = export_samples(a.data)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"exported={info['exported']} skipped_pending={info['pending']} -> {a.out}")
    print("提醒：desensitize 后再用于拟合；category 真值需人工补 labels.category。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
