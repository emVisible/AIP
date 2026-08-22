"""apa-core: Analytics 服务（设计文档 §13.1 apa-audit / §3.1 Analytics）。

从 Session journal 汇总运行指标：会话状态分布、动作成功率、耗时分位、
人工任务量。零依赖，供 APA-Studio /api/analytics 与 CLI 使用。

    python -m apa_core.analytics --journals 'data/*.jsonl'
"""
from __future__ import annotations

import glob
from pathlib import Path
from typing import Dict, List, Optional

from .persist import journal_records


def summarize(journal_paths: List[str], *, tenant: Optional[str] = None) -> dict:
    expanded: List[str] = []
    for p in journal_paths:
        expanded.extend(glob.glob(p))
    sessions: Dict[str, dict] = {}
    actions: Dict[str, dict] = {}   # action_id -> {name, source, risk, sent_ms}
    results: List[dict] = []
    tasks_open = 0
    tasks_resolved = 0

    for path in expanded:
        for rec in journal_records(path):
            if tenant and rec.get("tenant") != tenant:
                continue
            kind = rec.get("kind")
            sid = rec.get("session", "?")
            s = sessions.setdefault(sid, {"state": "INITIALIZING",
                                          "tenant": rec.get("tenant"),
                                          "actions": 0})
            if kind == "state":
                s["state"] = rec.get("to", s["state"])
            elif kind == "action":
                s["actions"] += 1
                actions[rec.get("action_id", "")] = {
                    "name": rec.get("name"), "source": rec.get("source"),
                    "risk": rec.get("risk"), "sent_ms": rec.get("ts"),
                }
            elif kind == "action_result":
                meta = actions.get(rec.get("action_id", ""), {})
                results.append({
                    "status": rec.get("status"),
                    "name": meta.get("name"),
                    "risk": meta.get("risk"),
                    "duration_ms": rec.get("duration_ms"),
                })
            elif kind == "task":
                if rec.get("status") == "resolved" or rec.get("outcome"):
                    tasks_resolved += 1
                    tasks_open = max(0, tasks_open - 1)
                else:
                    tasks_open += 1

    by_state: Dict[str, int] = {}
    for s in sessions.values():
        by_state[s["state"]] = by_state.get(s["state"], 0) + 1

    terminal = [r for r in results if r["status"] in ("ok", "failed", "timeout")]
    ok = sum(1 for r in terminal if r["status"] == "ok")
    durations = sorted(r["duration_ms"] for r in terminal
                       if r.get("duration_ms") is not None)

    def pct(p: float) -> Optional[int]:
        if not durations:
            return None
        idx = min(len(durations) - 1, int(round(p / 100 * (len(durations) - 1))))
        return durations[idx]

    by_risk_fail: Dict[str, int] = {}
    for r in terminal:
        if r["status"] != "ok":
            k = r.get("risk") or "?"
            by_risk_fail[k] = by_risk_fail.get(k, 0) + 1

    return {
        "sessions": {
            "total": len(sessions),
            "by_state": by_state,
        },
        "actions": {
            "sent": len(actions),
            "terminal": len(terminal),
            "ok": ok,
            "success_rate": round(ok / len(terminal), 4) if terminal else None,
            "failures_by_risk": by_risk_fail,
            "duration_ms": {"p50": pct(50), "p95": pct(95)},
        },
        "human_tasks": {"open": tasks_open, "resolved": tasks_resolved},
    }


def report(data: dict) -> str:
    """人类可读报告。"""
    lines: List[str] = ["== APA Analytics =="]
    sess = data["sessions"]
    lines.append(f"Sessions: {sess['total']}")
    for state, n in sorted(sess["by_state"].items()):
        lines.append(f"  {state:<12} {n}")
    act = data["actions"]
    rate = f"{act['success_rate']:.1%}" if act["success_rate"] is not None else "n/a"
    lines.append(f"Actions: sent={act['sent']} terminal={act['terminal']} "
                 f"ok={act['ok']} success={rate}")
    d = act["duration_ms"]
    if d["p50"] is not None:
        lines.append(f"Duration: p50={d['p50']}ms p95={d['p95']}ms")
    if act["failures_by_risk"]:
        lines.append(f"Failures by risk: {act['failures_by_risk']}")
    t = data["human_tasks"]
    lines.append(f"Human tasks: open={t['open']} resolved={t['resolved']}")
    return "\n".join(lines)


def main() -> int:  # pragma: no cover
    import argparse
    parser = argparse.ArgumentParser(prog="analytics", description="APA 运行指标")
    parser.add_argument("--journals", nargs="+", required=True)
    parser.add_argument("--tenant", default=None)
    args = parser.parse_args()
    data = summarize(args.journals, tenant=args.tenant)
    print(report(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())