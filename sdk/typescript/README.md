# AIP — TypeScript SDK (Kernel v0.1)

TypeScript mirror of the AIP Kernel (see `SPEC.md`): the four message
types, per-stream sequencing, action lifecycle & idempotency, sessions
with cursors, and transports (in-memory + WebSocket binding).

```ts
import { AIPPeer, InMemoryEndpoint } from "@aip/protocol";

const peer = new AIPPeer("rpa_001", "s_001", { transport: endpoint });

peer.sendEvent("button.appeared", { id: "confirm" });
peer.sendResult("ok", "act_123", { data: { page: "payment" } });
```

## Build & test

```bash
npm install
npm run build        # tsc -> dist/
npm test             # node:test on dist/test/ (schema conformance + E5 framing)
```

## What the tests verify

- `test/schema-conformance.test.ts` — validates the **same** schema-kind
  fixtures as the Python runner (`conformance/tests/*.json` against
  `schema/aip.json`, via ajv). Cross-language conformance: a message the
  Python SDK accepts, the TS SDK accepts too.
- `test/e5-framing.test.ts` — SPEC §10 E5: one JSON object per WebSocket
  text frame, plus a real ws server↔client round trip.

## Transport

- `InMemoryEndpoint` / `connectEndpoints` — for tests and local demos.
- `WsServerTransport` / `WsClientTransport` — WebSocket binding (the only
  Kernel binding, SPEC §7.1). Frame-level errors surface via `onError`.

This SDK implements the Kernel only. Context-on-Demand, Action Registry,
and Policy are profiles (SPEC §9) — build them on top, matching the
Python SDK.