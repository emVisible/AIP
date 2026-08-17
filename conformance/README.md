# AIP Conformance

The conformance suite makes "AIP/1.0 Conformant" a checkable claim
(SPEC §10). Any implementation — Python, Go, Rust, TypeScript, Java —
can run the same tests.

## Layout

```
conformance/
├── run.py                 ← schema-level test runner (no harness needed)
├── tests/
│   ├── e-envelope.json    ← E: envelope & wire
│   ├── m-messages.json    ← M: the four message types
│   ├── s-sequence.json    ← S: per-stream sequence & ordering
│   ├── a-lifecycle.json   ← A: action lifecycle & idempotency
│   ├── d-delivery.json    ← D: cursors, resume, heartbeat
│   └── k-security.json    ← K: security & invariants
```

## Test kinds

| Kind | Runs | Needs |
|------|------|-------|
| `schema` | statically, with any JSON Schema (draft-07) validator | only `schema/aip.json` |
| `behavior` | against the reference Gateway (`examples/hello-rpa/gateway.py`) | the Python SDK (no external deps) |

### Run everything

```bash
pip install jsonschema          # only needed for the schema-level runner
python3 conformance/run.py      # schema + behavior; prints overall verdict
python3 conformance/run.py --skip-behavior   # schema only
```

Expected verdict: `ALL CONFORMANT` — 9 schema tests + 21 behavior tests
pass. The last remaining SKIP (E5, WebSocket framing) is covered by the
TypeScript SDK's `test/e5-framing.test.ts` (SPEC §10 E5: one JSON object
per text frame), which also runs a real ws server↔client round trip.

### Cross-language conformance

The TypeScript SDK (`sdk/typescript`) validates the **same** schema-kind
fixtures against `schema/aip.json` with ajv, and implements the E5
framing rule:

```bash
cd sdk/typescript
npm install
npm test    # schema conformance (18/18) + E5 framing
```

A message the Python SDK accepts is accepted by the TypeScript SDK, and
vice versa.

### Schema tests

The schema runner validates each message against `schema/aip.json` and
maps failures to kernel error codes (`UNSUPPORTED_VERSION`,
`INVALID_MESSAGE`, …).

### Behavior tests

Behavior tests replay scripted messages through the reference Gateway
and assert the `expect` keywords. Fault-injection `steps` make the
reliability tests (A5/A6, D2–D5) runnable:

| Fault step | Effect |
|------------|--------|
| `{"fault": "advance", "ms": 6000}` | advance the gateway's fake clock and fire timeouts/retries |
| `{"fault": "disconnect", "side": "executor"}` | drop a connection mid-flow |
| `{"fault": "reconnect", "side": "agent", "cursors": {...}}` | reconnect; re-deliver buffered outbound beyond the cursors |
| `{"fault": "ping"}` | heartbeat; must not consume application seq |

| `expect` keyword | Meaning |
|------------------|---------|
| `applied` | number of messages the peer applied (int, or per-stream map) |
| `executions` | number of times an action was actually executed |
| `errors` / `error` | error codes emitted by the peer |
| `outcome` | terminal outcome keyword (`ok`, `duplicate_ignored`, `rejected`, …) |
| `duplicate_reply` | the exact terminal result expected for a duplicate id |
| `retries` / `ids_used` | retry behavior (must reuse the same action id) |
| `final_state` | action lifecycle state (`SUCCESS`, `TIMEOUT`, …) |
| `resumed` / `ids_preserved` | resume re-delivery (seqs beyond the cursor, original ids) |
| `state_preserved` | connection drop did not change execution state |
| `seq_advanced_by_heartbeat` | heartbeat did not consume application seq |
| `cursors_accepted` | hello returns per-stream cursors, not one number |
| `invariant` | the SPEC invariant the test guards (I2, I3, I6, I8, I9, I10) |

A harness that passes every test in this suite — schema and behavior —
may claim:

```
AIP/1.0 Conformant
```

The reference harness lives in `conformance/harness.py` and targets the
reference Gateway. Other implementations can run the same fixtures
against their own harness.

## Writing a test

Tests are JSON. A schema test:

```json
{
  "id": "M2",
  "kind": "schema",
  "description": "Actions must not carry idempotency overrides.",
  "cases": [
    { "input": { "...": "valid action" }, "expect": { "valid": true } },
    { "input": { "...": "action with idempotency" }, "expect": { "valid": false, "error": "INVALID_MESSAGE" } }
  ]
}
```

A behavior test:

```json
{
  "id": "S2",
  "kind": "behavior",
  "description": "Duplicates are ignored and never re-executed.",
  "steps": [ { "send": { "...": "action" } }, { "send": { "...": "same action again" } } ],
  "expect": { "applied": 1, "executions": 1, "outcome": "duplicate_ignored" }
}
```

Each test guards one requirement from SPEC §10. Do not add tests for
features outside the Kernel; extension profiles get their own suites.

## Governance

Adding a conformance requirement is amending the protocol. Per the
complexity budget (SPEC §9.1), a new test must cite the
interoperability or correctness failure it prevents.
