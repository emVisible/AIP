#!/usr/bin/env python3
"""AIP cost benchmark driver (SPEC App. E).

Runs the five implementations over the ERP task in simulation mode
(scripted decisions, equalized success) and reports context efficiency
and cost per successful task.

Usage:
    python3 -m benchmarks.run            # from repo root
"""
import json
from pathlib import Path

from benchmarks.agents import ALL_MODELS  # noqa: E402
from benchmarks.models import PRICING  # noqa: E402
from benchmarks.task import STEPS  # noqa: E402


def run() -> dict:
    rows = []
    for cls in ALL_MODELS:
        agent = cls().run(STEPS)
        success = 1.0  # scripted decisions -> all tasks succeed (equalized)
        cost_per_task = agent.cost / success
        rows.append(
            {
                "model": cls.name,
                "calls": agent.calls,
                "tier_calls": agent.tier_calls,
                "input_tokens": agent.total_in,
                "output_tokens": agent.total_out,
                "total_tokens": agent.total_tokens,
                "avg_context_per_decision": round(agent.avg_context, 1),
                "cost_usd_per_task": round(agent.cost, 6),
                "cost_per_successful_task": round(cost_per_task, 6),
                "success_rate": success,
            }
        )
    return {"task": "erp_submit_order", "steps": len(STEPS), "pricing": PRICING, "results": rows}


def render_table(results: dict) -> str:
    r = results["results"]
    headers = ["model", "calls", "in", "out", "total", "avg ctx", "$/task"]
    widths = {}
    lines = []
    cells = []
    for row in r:
        model = row["model"]
        cells.append(
            [
                model,
                str(row["calls"]),
                f"{row['input_tokens']:,}",
                f"{row['output_tokens']:,}",
                f"{row['total_tokens']:,}",
                f"{row['avg_context_per_decision']:,.0f}",
                f"${row['cost_per_successful_task']:.4f}",
            ]
        )
    col_w = [max(len(h), *(len(c[i]) for c in cells)) for i, h in enumerate(headers)]
    def fmt(cells_): return " | ".join(c.ljust(col_w[i]) for i, c in enumerate(cells_))
    lines.append(fmt(headers))
    lines.append(" | ".join("-" * w for w in col_w))
    for c in cells:
        lines.append(fmt(c))
    lines.append("")
    base = r[0]["cost_per_successful_task"]
    for row in r[1:]:
        other = max(row["cost_per_successful_task"], 1e-9)
        if other <= base:
            ratio = base / other
            lines.append(f"  vs A: {row['model']} = {ratio:,.0f}x cheaper")
        else:
            ratio = other / base
            lines.append(f"  vs A: {row['model']} = {ratio:,.0f}x more expensive")
    return "\n".join(lines)


def main() -> int:
    results = run()
    print(f"task: {results['task']} ({results['steps']} decisions, scripted, success=100%)")
    print(f"pricing ($/1M tokens): {results['pricing']}\n")
    print(render_table(results))
    out = Path(__file__).resolve().parent / "result.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())