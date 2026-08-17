# Changelog

All notable changes to AIP follow this file. Format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The protocol itself is versioned independently of SDKs: the wire version
(`v` in the envelope) stays `1` for the Kernel; SDK packages track the
release version.

## [0.1.0] — 2026-08-17

First public release. AIP Kernel v0.1 — a minimal protocol for reliable,
state-driven interaction between a decision engine and an executor.

### Added

- **Specification** (`SPEC.md`): Kernel v0.1 — 4 message types (`event`,
  `action`, `result`, `error`), 9-field envelope, per-`(session, source)`
  sequencing, action lifecycle (accepted/running → terminal), cursors &
  resume, 10 invariants, error registry, complexity budget, conformance,
  extensions & profiles (Context-on-Demand, Action Registry, Policy,
  Decision Routing, MCP/A2A integration).
- **Schema** (`schema/aip.json`): JSON Schema (draft-07) for the envelope
  and the four message types.
- **Conformance** (`conformance/`): 31 language-agnostic test cases
  (E/M/S/A/D/K groups) with a Python runner — 9 schema tests + 21
  behavior tests against the reference gateway (fault-injection covers
  timeout, retry, resume, heartbeat, security); TypeScript SDK re-runs
  the same schema fixtures.
- **Python SDK** (`sdk/python`): messages, per-stream sequencing, action
  lifecycle & idempotency store, sessions/cursors, in-memory transport,
  WebSocket binding (`aip[ws]`), Context-on-Demand (`ContextStore`),
  Action Registry, injectable clock.
- **TypeScript SDK** (`sdk/typescript`): Kernel mirror with in-memory +
  WebSocket transports and E5 framing tests.
- **Reference implementation** (`examples/hello-rpa`): rule agent +
  reference gateway + scripted executor completing a submit-order flow
  end to end, including an on-demand context round trip.
- **Benchmark** (`benchmarks/`): cost-per-successful-task experiment
  (SPEC Appendix E) — AIP + Context-on-Demand 13x cheaper than a
  long-context agent on the reference task; rule cascade 93x cheaper.
- **Integration reference** (`INTEGRATION.md`): executor & agent guide —
  roles, semantic adapter, action contract, idempotency, deployment,
  wiring, testing, pitfalls, FAQ.

### Design decisions (SPEC Appendix C)

- Async-only core; synchronous experience is a correlation special case
  (C.10) — no dual-mode semantics in the protocol.
- Context access is an action (`context.get`), never a message type (C.9).
- The Kernel defines zero actions; registries are executor-defined (C.4).

### Testing

- Python: 9 schema + 21 behavior conformance tests, ContextStore (8),
  WebSocket/E5 (7) — all passing.
- TypeScript: 18/18 schema fixtures + E5 framing — all passing.

[0.1.0]: https://github.com/OWNER/aip/releases/tag/v0.1.0
