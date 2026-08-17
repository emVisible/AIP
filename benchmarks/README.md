# AIP Cost Benchmark

The decisive experiment from SPEC §15.2 / Appendix E: does
*short messages + externalized state + Context-on-Demand* materially
lower automation cost?

## Run

```bash
python3 -m benchmarks.run
```

Writes `benchmarks/result.json` and prints the comparison table.

## Task

`erp_submit_order` — auto-login to ERP → query order → modify status →
submit → fetch result. 9 decisions, defined in `task.py`.

## Methodology

The five implementations from SPEC Appendix E produce the **same scripted
decisions**, so success rate is equalized at 100% **by construction**.
The benchmark therefore measures **context efficiency and cost per
successful task**, not reasoning quality.

| Model | Context model |
|-------|---------------|
| **A** traditional long-context agent | system + page + *growing transcript* every decision |
| **B** MCP agent | tool schemas + page + *growing observation log* every decision |
| **C** AIP + Context-on-Demand | per-decision minimal event packet; only needed fields fetched |
| **D** C + small model | complex decision → LLM; the rest → small model |
| **E** C + rule + small + LLM | deterministic steps cost **zero** tokens |

Token counting: `est_tokens` (len(json)/4, `models.py`). Pricing is
illustrative USD-per-1M-token constants (`models.py::PRICING`) — adjust
to your providers. Context-building constants (`models.py::CONTEXT`)
model a realistic page/toolset; tune to your deployment.

## Reading the output

Headline metric is **cost per successful task** (last column + `$/task`),
never cost per LLM call. The 2026-08-17 simulation run shows:

```
A (long-context):        $0.1027/task   (avg context 2,103 tokens/decision)
B (MCP):                 $0.2142/task   (tool schemas dominate — 2x more expensive than A)
C (AIP + Context):       $0.0080/task   13x cheaper than A
D (AIP + small model):   $0.0014/task   74x cheaper than A
E (AIP + rule cascade):  $0.0011/task   93x cheaper than A
```

These ratios are illustrative of the *mechanism*, not a guarantee:
real deployments change the constants, and the one number that matters is
measured below.

## Pass condition

AIP is only a success if the context/cost reduction holds **at equivalent
task success rate**. The pass condition (SPEC §15.2):

> **context reduction at equivalent success rate** — not a raw byte target.

In simulation mode success is equalized by construction. In real-API mode
you must measure success rate separately and only compare models whose
success rates are statistically equivalent.

## Real-API mode (TODO)

Replace scripted decisions with actual model calls:

1. In each agent's `decide()`, call your provider instead of returning
   `(tokens_in, tokens_out, tier)`.
2. Record real token usage from the provider response.
3. Track success per step; keep the pass-condition rule above.
4. Optionally measure latency and failure/recovery rate per SPEC §15.2.