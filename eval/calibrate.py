"""拟合各问题温度 T：持出样本 NLL 最小。

    python3 -m eval.calibrate --samples eval/samples_example.jsonl
    python3 -m eval.calibrate --samples /path/to/your.jsonl --out eval/calibration.json

要求 sidecar 在跑（无模型拟合无意义，缺席直接失败，不静默）。
标签推导（expected==review 的行跳过：弃权类不可标定）：
  is_spam/toxic/fraud/sensitive：reject→1，approve→0
  severity：approve→level 0，reject→level 2
  category：跳过，除非行内带 labels.category 真值（真实样本可提供）
输出 {qid: {T, n, nll_before, nll_after}}；样本不足（单边）的 qid 不写入，
运行时按 T=1（出厂）处理。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clearance_core.calibration import (  # noqa: E402
    fit_temperature_binary, fit_temperature_categorical)
from clearance_core.questions import build_review_questions  # noqa: E402
from eval.sweep import load_samples  # noqa: E402

SIDECAR = os.environ.get("LAYA_SIDECAR_URL", "http://127.0.0.1:8685")
NOULS = ("is_spam", "toxic", "fraud", "sensitive")


def ask_sidecar(kind: str, text: str, questions: dict) -> dict:
    req = urllib.request.Request(
        SIDECAR + "/decide",
        data=json.dumps({"kind": kind, "text": text, "questions": questions}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
    except Exception as e:
        print(f"ERROR: sidecar 不可达（{e}）。先起 sidecar：cd laya_sidecar && uv run python server.py")
        raise SystemExit(1)
    if not res.get("ok"):
        print(f"ERROR: sidecar 失败：{res.get('error')}")
        raise SystemExit(1)
    return res["answers"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--samples", required=True)
    p.add_argument("--out", default="eval/calibration.json")
    a = p.parse_args()
    rows = [r for r in load_samples(a.samples) if r["expected"] in ("approve", "reject")]
    skipped = len(load_samples(a.samples)) - len(rows)
    print(f"fit rows={len(rows)} skipped_review={skipped} (review 类不可标定)")

    questions = build_review_questions()
    pairs: dict = {q: [] for q in NOULS}
    sev_rows: list = []
    cat_rows: list = []
    for r in rows:
        ans = ask_sidecar(r.get("kind", "other"), r.get("title", "") + "\n" + r.get("body", ""),
                          questions)
        y = 1 if r["expected"] == "reject" else 0
        for q in NOULS:
            try:
                pairs[q].append((float(ans[q]["noul"]), y))
            except (KeyError, TypeError, ValueError):
                pass
        try:
            sev_rows.append((ans["severity"]["probabilities"], str(2 * y)))
        except (KeyError, TypeError):
            pass
        true_cat = (r.get("labels") or {}).get("category")
        if true_cat:
            try:
                cat_rows.append((ans["category"]["probabilities"], true_cat))
            except (KeyError, TypeError):
                pass

    table = {}
    for q in NOULS:
        T, before, after = fit_temperature_binary(pairs[q])
        n1 = sum(1 for _, y in pairs[q] if y == 1)
        print(f"{q:10s} T={T:5.2f} n={len(pairs[q]):3d}(pos={n1}) NLL {before:.3f}->{after:.3f}")
        if T != 1.0:
            table[q] = {"T": T, "n": len(pairs[q]), "nll_before": before, "nll_after": after}
    for qid, fit_rows in (("severity", sev_rows), ("category", cat_rows)):
        T, before, after = fit_temperature_categorical(fit_rows)
        print(f"{qid:10s} T={T:5.2f} n={len(fit_rows):3d} NLL {before:.3f}->{after:.3f}")
        if T != 1.0 and fit_rows:
            table[qid] = {"T": T, "n": len(fit_rows), "nll_before": before, "nll_after": after}

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=1)
    print(f"wrote {a.out} ({len(table)} questions fitted; 其余 T=1 出厂值)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
