"""阈值 sweep：无副作用（只调 decide + route，不写 store），stdlib only。

用法：
    cd clearance
    python3 -m eval.sweep eval/samples_example.jsonl
    python3 -m eval.sweep /path/to/your_samples.jsonl --thresholds 0.7,0.8,0.85,0.9
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clearance_core import gateway  # noqa: E402
from clearance_core.decide import decide  # noqa: E402
from clearance_core.models import ReviewItem, new_id  # noqa: E402

EXPECT2FINAL = {"approve": "review.approve", "reject": "review.reject",
                "review": "human.task.create"}


def load_samples(path: str) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            assert r.get("expected") in EXPECT2FINAL, f"line {i}: bad expected"
            rows.append(r)
    return rows


def run(rows: list, threshold: float) -> dict:
    correct = auto = human = auto_err = 0
    errs = []
    for i, r in enumerate(rows):
        item = ReviewItem(new_id("ev"), r.get("kind", "other"),
                          r.get("title", ""), r.get("body", ""))
        d = decide(item)
        final, _ = gateway.route(d.action, d.confidence, threshold)
        want = EXPECT2FINAL[r["expected"]]
        if final == "human.task.create":
            human += 1
            if want != "human.task.create":
                errs.append((i, "human_but_should_auto", r["title"][:30]))
            else:
                correct += 1
        else:
            auto += 1
            if final == want:
                correct += 1
            else:
                auto_err += 1
                errs.append((i, f"auto_{final.split('.')[-1]}_but_want_{want.split('.')[-1]}",
                             r["title"][:30]))
    n = len(rows)
    return {"threshold": threshold, "n": n,
            "accuracy": correct / n, "auto_rate": auto / n,
            "human_rate": human / n, "auto_errors": auto_err, "errs": errs}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("samples")
    p.add_argument("--thresholds", default="0.70,0.75,0.80,0.85,0.90,0.95")
    a = p.parse_args()
    rows = load_samples(a.samples)
    print(f"samples={len(rows)} engine={'laya' if __import__('importlib').util.find_spec('laya') else 'heuristic'}")
    print(f"{'thr':>6} {'acc':>6} {'auto':>6} {'human':>6} {'auto_err':>9}")
    best = None
    results = []
    for t in [float(x) for x in a.thresholds.split(",")]:
        r = run(rows, t)
        results.append(r)
        print(f"{t:>6.2f} {r['accuracy']:>6.2f} {r['auto_rate']:>6.2f} "
              f"{r['human_rate']:>6.2f} {r['auto_errors']:>9d}")
        if best is None or (r["auto_errors"], -r["accuracy"]) < (best["auto_errors"], -best["accuracy"]):
            best = r
    print(f"\nrecommended threshold={best['threshold']:.2f} "
          f"(acc={best['accuracy']:.2f} auto={best['auto_rate']:.2f} auto_err={best['auto_errors']})")
    if best["errs"]:
        print("errors at recommended:")
        for i, kind, title in best["errs"]:
            print(f"  sample#{i} {kind}: {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
