# AIP — AI Interaction Protocol

> AIP is a minimal protocol for reliable, state-driven interaction between
> a decision engine and an executor. Its primary optimization target is
> **minimum sufficient context per decision**, not minimum message size.

AIP turns an LLM from a *long-context chat endpoint* into a *decision
node*: it receives a minimal event/state packet, produces one decision,
and returns it as a short, structured message. The loop:

```
E → D → A → R      Event → Decision → Action → Result → Event ...
```

- **Event** — a semantic fact that happened (never telemetry, never chat)
- **Decision** — inside the decision engine (rule / small model / LLM / human)
- **Action** — a named capability invocation, executed reliably
- **Result** — the objective outcome (accepted/running → ok/failed/timeout/rejected)

The protocol defines only how components exchange **minimal, reliable,
verifiable** state and actions. It does not replace MCP (capability) or
A2A (agent interop); it fills the decision-engine ↔ executor boundary.

## Specification

[`SPEC.md`](SPEC.md) — the Kernel v0.1 spec: 4 message types, 9 envelope
fields, per-stream sequencing, action lifecycle, cursors & resume,
10 invariants, error registry, extensions, conformance.

[`INTEGRATION.md`](INTEGRATION.md) — executor & agent integration
reference: roles, semantic adapter, action contract, idempotency,
Context-on-Demand, deployment, wiring, testing, pitfalls, FAQ.

## Repository

```
SPEC.md                    ← the protocol (read this first)
schema/aip.json            ← JSON Schema for the envelope + 4 messages
conformance/               ← schema + behavior test suite (reference gateway)
sdk/python/                ← Python SDK (Kernel + Context-on-Demand + ws binding)
sdk/typescript/            ← TypeScript SDK (incl. E5 framing tests)
examples/hello-rpa/        ← end-to-end demo: agent + gateway + executor
benchmarks/                ← cost-per-successful-task experiment (SPEC App. E)
```

## Quick start

```bash
# conformance (Python, no deps for behavior tests)
python3 conformance/run.py            # → overall: ALL CONFORMANT

# end-to-end demo
python3 examples/hello-rpa/run.py     # → RESULT: OK — order submitted

# cost benchmark
python3 -m benchmarks.run             # → AIP cascade 93x cheaper than long-context

# TypeScript SDK (cross-language conformance + E5 framing)
cd sdk/typescript && npm install && npm test
```

## Status

Kernel v0.1 is implemented, tested, and benchmarked in simulation:

| | Result |
|---|---|
| Schema conformance (Python + TS, same fixtures) | 18/18 |
| Behavior conformance (reference gateway) | 21/21 + E5 (TS + Python ws) |
| hello-rpa end-to-end (incl. Context-on-Demand) | passes |
| Cost per successful task | AIP 13x–93x cheaper than long-context agent |

Roadmap (SPEC §15): real-API benchmark mode, HTTP binding, more executor
adapters, MCP capability-gateway integration.

## License

MIT — see [`LICENSE`](LICENSE).
