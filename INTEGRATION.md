# AIP Integration Reference — Executor & Agent

> This document is the **integration reference** for the AIP Kernel v0.1.
> It expands the executor-side and agent-side concepts of the protocol
> into operational guidance for implementers. The normative source is
> `SPEC.md`; this document adds no new requirements.
> Code shown is reference implementation (`sdk/python`, `sdk/typescript`,
> `examples/hello-rpa`).

---

## Table of Contents

1. [Purpose & Scope](#1-purpose--scope)
2. [Core Concepts](#2-core-concepts)
3. [The Wire Contract](#3-the-wire-contract)
4. [Executor Guide](#4-executor-guide)
5. [Agent (Decision Engine) Guide](#5-agent-decision-engine-guide)
6. [Topology & Security](#6-topology--security)
7. [Deployment Guide](#7-deployment-guide)
8. [Worked Example: Full Message Transcript](#8-worked-example-full-message-transcript)
9. [Integration Recipes](#9-integration-recipes)
10. [Common Pitfalls](#10-common-pitfalls)
11. [Testing Your Integration](#11-testing-your-integration)
12. [Error Handling Reference](#12-error-handling-reference)
13. [FAQ](#13-faq)
14. [Integration Checklist](#14-integration-checklist)
15. [Glossary](#15-glossary)
16. [Appendix](#16-appendix)

---

## 1. Purpose & Scope

AIP is a minimal protocol for reliable, state-driven interaction between
a **decision engine** and an **executor**. This document answers the two
practical questions an implementer has:

1. **"I am the executor side"** — how do I turn my RPA/browser/ERP/API
   client into an AIP participant?
2. **"I am the agent side"** — how do I connect my LLM service / rule
   engine to an AIP executor?

Everything below is grounded in the reference SDKs. The Kernel only
defines messages, ordering, action lifecycle, and delivery semantics;
policy, registries, and context are profiles with reference
implementations.

---

## 2. Core Concepts

### 2.1 Three participants

```
         AIP messages
   ┌───────────────┐        ┌───────────────────┐
   │ Decision      │  <──>  │ Executor          │   peer-to-peer (valid)
   │ Engine (Agent)│        │ (RPA / Browser /  │
   └──────┬────────┘        │  ERP / API)       │
          │                 └─────────┬─────────┘
          └──────────── Gateway ──────┘   optional intermediary
```

| Participant | Responsibility | Required |
|-------------|----------------|----------|
| **Decision Engine** | consumes events → decides → emits actions | one end |
| **Executor** | executes actions → returns results; lifts reality into semantic events | one end |
| **Gateway** | optional mediator: policy, dedup, retry, resume, audit | optional (SPEC §2: peer-to-peer must remain valid) |

> The agent is a **compute node, not a state store**. The gateway is
> **not** required; direct agent ↔ executor connections are fully legal.

### 2.2 The core loop

```
EVENT → DECISION → ACTION → RESULT → EVENT → ...
```

Exactly four message types exist: `event`, `action`, `result`, `error`.
Every additional capability (context access, approval, progress) is
expressed as an **action + result**, never as a new message type.

### 2.3 Semantic boundaries (must not blur)

| Type | Meaning | Never |
|------|---------|-------|
| `event` | a fact that happened (observational, never imperative) | "please click the button" |
| `action` | a request to execute (imperative, never observational) | "I think we should click" |
| `result` | the objective outcome of an action | what was *intended* |
| `error` | a protocol/transport/processing anomaly | business failure (that is `result.failed`) |

---

## 3. The Wire Contract

### 3.1 Envelope (9 fields, 7 required)

```json
{
  "v": 1,                       // protocol version (must be 1)
  "type": "event",              // event | action | result | error
  "id": "evt_123",              // unique within stream; resends keep the id
  "in_reply_to": null,          // result: required (the action id); event: must be absent
  "session": "s_001",
  "seq": 7,                     // sender's (session, source) stream, increasing
  "ts": 1786944500123,          // informational only — never for ordering/timeouts (I8)
  "source": "rpa_001",          // participant identity, bound to the authenticated principal (I9)
  "payload": { }
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `v` | yes | Kernel v0.1 = `1` |
| `type` | yes | exactly one of the four |
| `id` | yes | unique within `(session, source)` at minimum; ULID/UUID recommended |
| `in_reply_to` | no | correlation; rules per type below |
| `session` | yes | execution context; outlives connections |
| `seq` | yes | sender-assigned, per-stream, starting at 1 |
| `ts` | yes | epoch ms; informational (I8) |
| `source` | yes | authenticated participant identity |
| `payload` | yes | type-specific |

`in_reply_to` rules:

| Message | `in_reply_to` |
|---------|---------------|
| `event` | MUST be absent |
| `action` | MAY reference the triggering event |
| `result` | MUST reference the action it answers |
| `error` | SHOULD reference the message it failed to process |

### 3.2 Sequence numbers

- **Sender**: each stream `(session, source)` numbers its own messages
  from 1, monotonically (the SDK's `AIPPeer` does this automatically;
  hand-built messages must set `seq` explicitly — `0` is rejected as
  out of order).
- **Receiver**: accept only `seq == last_applied + 1`; `seq <= last` with
  the same `id` is a **duplicate** (ignore, never re-execute); `seq <= last`
  with a new `id` is **stale** (reply `SEQ_OUT_OF_ORDER`); `seq > last + 1`
  is a **gap** (reply `SEQ_OUT_OF_ORDER`, never silently buffer).
- **Two senders in one session have independent streams** (I7). There is
  no global sequence.

### 3.3 Idempotency & retry — who does what

| Role | Obligation |
|------|------------|
| Executor | records `executed_action_ids`; a duplicate `action.id` is never re-executed and MUST return the previously recorded terminal outcome with `duplicate: true` + `original_result_id` |
| Gateway (if present) | decides retry on timeout from the Registry declaration; **reuses the same action id** on retry |
| Agent | retries only when the failure declares `retry.allowed`; never retries an `idempotency: none` action once execution may have started |

Idempotency is a property of the **action definition** (Registry), never
a per-call parameter (SPEC §4.2).

### 3.4 Heartbeat (binding level)

```
→ { "ping": { "session": "s_001" } }
← { "pong": { "session": "s_001" } }
```

- Heartbeats are transport-level and MUST NOT consume application `seq`
- A missed heartbeat = dead connection → hello + resume

### 3.5 Transport & encoding

- v0.1 standardizes exactly **one binding**: WebSocket + JSON (text
  frames; **one JSON document per frame** — E5 rule)
- A frame with two JSON objects, trailing garbage, or a non-object value
  is a frame-level error (surfaced via `on_error`), not a message
- In-memory transports (`Endpoint`/`Wire`) exist for tests and local demos
- Binary encodings and HTTP are future profiles (SPEC §9.7)

### 3.6 Cursors & resume

Each receiver tracks, per stream, the last **applied** sequence (its
cursor). On (re)connect, the binding handshake carries per-stream cursors:

```json
{ "hello": { "session": "s_001", "cursors": { "rpa_001": 102, "agent_001": 51 } } }
```

The sender resumes from `cursor + 1`, re-sending with **original id and
seq** — re-delivery is idempotent by construction: duplicates are
discarded, settled actions return stored outcomes.

**Connection ≠ session.** A disconnect MUST NOT change execution state
(I3).

---

## 4. Executor Guide

The executor turns your existing automation into an AIP participant:

```
reality ──semantic adapter──> semantic events (event)
actions ──mapping──> your automation functions ──> result
state ──maintain──> executed_action_ids / cursors / ContextStore
```

### 4.1 Hard obligations (7)

1. **Semantic lifting**: translate raw observations (DOM, mouse, API
   responses) into semantic events (§4.2)
2. **Semantic events only**: emit on business state changes, never
   telemetry (§4.3)
3. **Minimal state**: events carry only what a decision needs; large
   objects go behind a `context` reference (§4.4)
4. **Action contract**: reply `accepted` before long execution; MUST end
   with exactly one terminal result (§4.5)
5. **Idempotency**: maintain `executed_action_ids`; duplicates return the
   stored outcome (I2, §4.6)
6. **Stream order**: own `seq` strictly increasing (SDK handles it)
7. **Security**: `source` must match the authenticated principal;
   credentials never in payloads (I9/I10)

### 4.2 The semantic adapter — your most important design

Do **not** ship raw state to the decision engine. Lift it:

| ❌ Raw telemetry (forbidden) | ✅ Semantic event |
|---|---|
| `button.x=321, button.y=402` | `approval.required` |
| `DOM mutation #83921` | `page.state_changed` |
| `mouse.move` (every frame) | `payment.required` |

Lifting rules:
- Event name = **business state change** (dot-namespaced:
  `order.requires_review`, `ui.dialog.opened`)
- Attach `available_actions` when meaningful: the decision engine should
  never learn about your 200 other buttons
- Put identifiers and the minimum decision quantities in `data`; never a
  full document, screenshot, or DOM

### 4.3 When to emit

```
Emit when: a business-relevant state changed AND the decision engine
may need to change its decision.
```

```json
{
  "v": 1, "type": "event", "id": "evt_123",
  "session": "s_001", "seq": 7, "source": "rpa_001",
  "payload": {
    "name": "order.requires_review",
    "data": { "context": "ctx_order_1", "available_actions": ["approve", "reject"] }
  }
}
```

Rules:
- No `in_reply_to` (I4)
- Minimal `data`; large state via `context` reference (§4.4)
- Never "broadcast every frame" — event storms drown the decision engine
  (SPEC §9.9). Coalesce high-frequency state into a single semantic event.

### 4.4 Context-on-Demand (the executor owns the data)

```python
from aip import ContextStore

self.store = ContextStore()
self.store.put("ctx_order_1",
               {"order_id": "A12345", "status": "pending",
                "total": 299.0, "customer": "c_001"})
```

`context.get` is an **ordinary action** answered by a **normal result**:

```python
elif name == "context.get":
    data, err = self.store.get(params["ref"], params.get("fields"))
    if err:
        peer.send_result("failed", in_reply_to=action_id, code=err)  # context.not_found | context.expired
    else:
        peer.send_result("ok", in_reply_to=action_id,
                         data={"ref": params["ref"], "data": data})  # only requested fields
```

- Objects are addressable (`ref`), versioned (`put` bumps the version),
  and expiring (`ttl_ms` → `context.expired`)
- `get(ref, fields)` returns only requested fields — this is the
  protocol's central cost-reduction mechanism (SPEC §9.2)
- Failure codes live in the extension namespace (`context.not_found`),
  not in the Kernel error codes

### 4.5 The action execution contract (multi-result)

One action may produce several `result` messages: **non-terminal**
(progress) and **exactly one terminal**.

```
action  act_123
result  accepted   ← received, may take a while (non-terminal)
result  running    ← optional progress (non-terminal)
result  ok         ← terminal (one of these MUST arrive)
```

```python
def execute(self, action):
    action_id = action.id
    # ① reply accepted first (long tasks: prevents spurious timeouts)
    peer.send_result("accepted", in_reply_to=action_id)
    # ② run your automation
    ok, err = self.run_action(action.payload["name"], action.payload.get("params", {}))
    # ③ reply a terminal result
    if ok:
        peer.send_result("ok", in_reply_to=action_id, data={...})
    else:
        peer.send_result("failed", in_reply_to=action_id, code=err)
```

| `result.status` | Kind | Meaning |
|---|---|---|
| `accepted` / `running` | non-terminal | progress; can repeat; never last |
| `ok` / `failed` / `timeout` / `rejected` | terminal | exactly one; no further results for this action after it (I6) |

Edge cases:
- Precondition unmet → terminal `rejected` **before** execution; never
  half-execute
- No terminal result within the window → the gateway retries per the
  Registry (§3.3) — design actions to tolerate that (idempotency)

### 4.6 Idempotency obligations (I2 + stored outcome)

```
action act_123 executed, money moved, result lost
peer re-sends act_123 (same id)
```

The executor MUST:
1. maintain `executed_action_ids` for the session
2. never execute an already-executed id (I2)
3. on a duplicate, return the **recorded terminal outcome** with
   `duplicate: true` + `original_result_id`

```python
if action_id in self.executed:
    status, original = self.outcomes[action_id]
    peer.send_result(status, in_reply_to=action_id,
                     duplicate=True, original_result_id=original)
    return
```

### 4.7 Expressing failure: `result.failed` vs `error`

| Situation | Use | Example |
|---|---|---|
| Action failed (business/target layer) | `result.failed` + executor-defined code | `{status:"failed", code:"target_not_found"}` |
| Message itself invalid/out-of-order/unauthorized | `error` + Kernel code | `{code:"SEQ_OUT_OF_ORDER"}` |

- Executor failure codes: **lower-case, dot-namespaced**
  (`target_not_found`, `context.expired`) — never the 10 Kernel codes
- Retryability is **declared by the failing side**: `retry:
  {allowed: true, after_ms: 500}` — receivers never guess (SPEC C.7)

### 4.8 First thing on every message: classify

```python
def on_message(self, raw: dict):
    kind, msg = self.peer.handle(raw)     # accept | duplicate | stale | gap
    if kind != "accept":
        return                            # no side effects for the rest
    # handle msg
```

- `duplicate` → ignore (return stored outcome only for duplicate actions)
- `stale` / `gap` → reply `error SEQ_OUT_OF_ORDER`

### 4.9 Declaring your Action Registry

Actions are named capability invocations (`browser.click`,
`erp.order.approve`). The Kernel defines **zero** actions; the executor
declares its own registry — which is also what the gateway consults for
idempotency/timeout/retry:

```python
from aip import ActionRegistry

registry = (
    ActionRegistry()
    .register("browser.click",      idempotency="none",     timeout_ms=5000)
    .register("erp.order.approve",  idempotency="required", timeout_ms=5000, retries=1)
    .register("context.get",        idempotency="required", timeout_ms=5000)
)
```

| Registry field | Meaning |
|---|---|
| `idempotency` | `required` (safe & deduped) / `optional` / `none` (never retry after execution may have started) |
| `timeout_ms` | delivery window; after it the gateway may retry (idempotent only) |
| `retries` | how many times the gateway re-delivers before giving up |

### 4.10 Session & cursor duties (executor view)

- Track your own send cursor per stream; on reconnect send `hello` with
  your receive cursors
- Re-deliver from `cursor + 1` with original id/seq
- Action state survives disconnects (I3)

---

## 5. Agent (Decision Engine) Guide

```
event ──> minimal-context prompt ──> decision ──> action
              ↑
    need more data? → context.get (fetch on demand)
```

### 5.1 Hard obligations

1. Consume **terminal results only** — `accepted`/`running` are progress,
   never business triggers
2. Fetch context **on demand** (`context.get`), never expect bulk payloads
3. Build actions with only `name/target/params/expect` — never carry
   `idempotency`/`risk` (the Registry decides)
4. Never guess retryability — trust `retry.allowed` from the failing side
5. Stay stateless about execution — state lives at the gateway/executor
6. Stay replaceable — rules, small models, LLMs, and humans all speak the
   same protocol; zero-LLM decisions are first-class

### 5.2 Decision loop

```python
def on_message(self, raw: dict):
    kind, msg = self.peer.handle(raw)
    if kind != "accept":
        return
    if msg.type == "event":
        self._decide(msg)
    elif msg.type == "result":
        self._on_result(msg)

def _decide(self, msg):
    payload = msg.payload
    if payload["name"] == "order.requires_review":
        action = self.llm_decision(payload["data"], payload["data"]["available_actions"])
        self.peer.send_action(action["name"], target=action.get("target"),
                              in_reply_to=msg.id)
```

Minimal prompt pattern for LLM integration:

```
You are a decision executor. Output ONE JSON action: {"name","target","params"}.
Event: order.requires_review {context: ctx_order_1, available_actions: [approve, reject]}
Policy: approve is allowed only when total < 1000.
```

No chat history, no full DOM, no 200 tool schemas.

### 5.3 Context-on-Demand (agent usage)

```python
# ① the event carried only a reference
# ② fetch exactly what you need
action = self.peer.build_action(      # build → register → send (see §10 pitfall #1)
    "context.get",
    params={"ref": "ctx_order_1", "fields": ["order_id", "total", "customer"]},
    in_reply_to=evt_id,
)
self.pending_context = action.id
self.peer.send(action)

# ③ terminal result only (§5.4)
data = result_payload["data"]["data"]     # {"order_id": ..., "total": ..., ...}
```

### 5.4 Result handling: terminal only

```python
def _on_result(self, msg):
    status = msg.payload.get("status", "")
    if status in ("accepted", "running"):
        return                        # progress — keep waiting
    if status == "rejected":
        self.stop(msg.payload.get("code"))               # policy refused
        return
    if status in ("failed", "timeout"):
        retry = msg.payload.get("retry", {})
        if retry.get("allowed"):
            self.schedule_retry(retry.get("after_ms", 0))  # reuse the SAME action id
        return
    # status == "ok"
    self.consume(msg.payload.get("data", {}))
```

> Real-world lesson (hello-rpa): consuming `accepted` as a business
> result treated empty data as context ("approve unknown ($0)"). Non-
> terminal results never trigger business logic.

### 5.5 Zero-LLM routing (optional, recommended)

```
event → rule (deterministic)   → action      (0 model calls)
      → small model (simple)   → action
      → large LLM (complex)    → action
```

Example: `button.enabled == false` → rule answers `wait` without any
model call. The benchmark shows the rule cascade ≈ 93x cheaper than a
full-LLM agent for the reference task (`benchmarks/`).

---

## 6. Topology & Security

### 6.1 Direct vs gateway

```
Peer-to-peer: Agent <──WebSocket──> Executor    (valid; no policy/retry/audit)
With gateway: Agent <──> Gateway <──> Executor  (recommended in production)
```

The gateway is the **only** place policy and retry live. AI output is
untrusted input — validation happens at the gateway **before** execution,
never after. Reference gateway: `examples/hello-rpa/gateway.py`
(ordering, dedup/idempotency, lifecycle I6, policy, credential scan,
timeout/retry, resume — all conformance-tested).

### 6.2 Security baseline (both sides)

1. TLS 1.2+ on any network deployment; v0.1 recommends Bearer/OAuth2
   (mTLS permitted)
2. **source = authenticated identity** (I9): messages whose `source`
   does not match the handshake principal are rejected
3. **Credentials never in payloads** (I10): `password`, `Authorization`,
   `api_key`, cookies are forbidden in event/action/result/error payloads
   (the reference gateway scans and rejects)
4. Sessions carry TTLs; expired sessions reply `SESSION_EXPIRED`;
   multi-tenant isolation scopes session lookup by authenticated principal
5. Audit: every action logged (id, source, verdict, ts, outcome),
   append-only

---

## 7. Deployment Guide

### 7.1 What to run

| Component | Ship it? | Notes |
|-----------|----------|-------|
| Executor adapter | yes — your code | SDK does messages/seq/session |
| Agent service | yes — your code | rule / small / LLM behind one endpoint |
| Gateway | recommended | reference: `examples/hello-rpa/gateway.py` (Python) |
| Context store | executor-owned | `ContextStore` (Python) / implement in TS |

### 7.2 Wiring the reference gateway to real transports

The reference gateway is in-process logic: `gateway.receive(side, raw)`
returns outbound messages destined for the **other** side. To run it as
a service, maintain two connections (one per side) and route outbound
from each side to the *other* side's socket:

```python
import asyncio, json
from gateway import Gateway

class GatewayService:
    def __init__(self):
        self.gateway = Gateway("s_erp_001",
                               identities={"executor": "rpa_001", "agent": "agent_001"},
                               policy={"require_approval": []})
        self.conns = {}          # side -> websocket

    async def session(self, side, ws):
        self.conns[side] = ws
        try:
            async for frame in ws:
                outbound = self.gateway.receive(side, json.loads(frame))
                other = "agent" if side == "executor" else "executor"
                target = self.conns.get(other)      # ← route to the OTHER side
                for m in outbound:
                    if target is not None:
                        await target.send(json.dumps(m.to_dict()))
        finally:
            self.conns.pop(side, None)

async def main():
    import websockets
    svc = GatewayService()                          # ← ONE service, shared
    async def handler(conn):                        # path distinguishes sides:
        await svc.session(conn.request.path.strip("/"), conn)
    server = await websockets.serve(handler, "0.0.0.0", 8080)
    await server.wait_closed()
```

> Production notes: terminate TLS at the gateway; authenticate each
> connection and bind `source` to the principal (I9) *before* routing
> anything; scope sessions per tenant; run policy as deploy-time
> configuration, not code. The two-connection routing above is exactly
> what the hello-rpa example does in-process (`deliver`).

### 7.3 Multiple streams / participants

One session may carry several senders (e.g. two agents or several RPA
instances) — each keeps its own `(session, source)` stream (I7). Cursors
are per stream, so resume works independently per participant.

### 7.4 Backpressure & event frequency

- Prefer **coalescing**: a high-frequency raw signal becomes one semantic
  event ("state settled on X") instead of N telemetry events
- If event rate still exceeds consumption, apply application-level rate
  limiting or queues at the executor; AIP itself has no flow control in
  v0.1 (backpressure is roadmap, SPEC §15.1)

### 7.5 Versioning & amendments

- Kernel additions require a **demonstrated interoperability or
  correctness failure** that cannot be solved as a profile (Complexity
  Budget, SPEC §9.1)
- New capabilities enter via **registries and profiles**, never new
  message types
- Conformance test additions are amendments: they must cite the failure
  they prevent (conformance/README.md)

---

## 8. Worked Example: Full Message Transcript

`submit_order` — the complete trace from `examples/hello-rpa/run.py`.
Two streams run in parallel; seq is per stream.

```
executor stream (rpa_001)            agent stream (agent_001)
─────────────────────────            ──────────────────────────
seq  1 event  button.appeared  ────►
                                     (decide)             seq  1 action browser.click  ────►
seq  2 result accepted        ────►
seq  3 result running         ────►
seq  4 result ok              ────►
seq  5 event  page.changed    ────►
seq  6 event  order.requires_review ────►   {context: ctx_order_1,
                                     available_actions:[approve,reject]}
                                     (decide: fetch on demand)   seq  2 action context.get ────►
seq  7 result accepted        ────►
seq  8 result running         ────►
seq  9 result ok (fields only)────►   {ref, data:{order_id,total,customer}}
                                     (decide: approve)      seq  3 action erp.order.approve ────►
seq 10 result accepted        ────►
seq 11 result running         ────►
seq 12 result ok              ────►
seq 13 event  order.submitted ────►   (decide: done)
```

Observe:
- The order data never crosses the wire except for the three requested
  fields (§4.4)
- Every action gets `accepted → running → ok` (multi-result contract)
- Cursors at the end: `{rpa_001: 13, agent_001: 3}` — and that is exactly
  what a reconnect would resume from

---

## 9. Integration Recipes

### 9.1 Recipe A — turn your existing automation into an executor (Python)

```python
import asyncio
from aip import AIPPeer, ContextStore
from aip.ws import WsClient   # pip install aip[ws]

SESSION = "s_erp_001"

class MyRpaAdapter:
    """Bridges AIP to your existing automation."""
    def __init__(self, transport):
        self.peer = AIPPeer(source="my_rpa_001", session_id=SESSION,
                            transport=transport)
        self.store = ContextStore()
        self.executed_ids = set()          # idempotency (I2)
        self.outcomes = {}                 # action_id -> (status, result_id)
        self.last_result_id = None
        # ... your automation handles (browser / ERP client)

    async def on_message(self, raw: dict):
        kind, msg = self.peer.handle(raw)
        if kind != "accept":
            return
        if msg.type == "action":
            await self._execute(msg)

    async def _execute(self, msg):
        action_id, name = msg.id, msg.payload["name"]
        params = msg.payload.get("params", {})
        if action_id in self.executed_ids:              # dedup: stored outcome
            status, original = self.outcomes[action_id]
            self.peer.send_result(status, in_reply_to=action_id,
                                  duplicate=True, original_result_id=original)
            return
        self.peer.send_result("accepted", in_reply_to=action_id)
        ok, data = await self.run_action(name, params)  # ← your capability
        self.executed_ids.add(action_id)
        self.outcomes[action_id] = ("ok" if ok else "failed", self.last_result_id)
        if ok:
            self.peer.send_result("ok", in_reply_to=action_id, data=data)
        else:
            self.peer.send_result("failed", in_reply_to=action_id, code=data)

    def emit(self, name, data=None):                    # call from business code
        self.peer.send_event(name, data)

transport = WsClient("ws://gateway:8080")
adapter = MyRpaAdapter(transport)

async def route(raw: dict):
    await adapter.on_message(raw)

transport.on_message = route
asyncio.run(transport.run())            # websockets receive loop
```

Your automation functions (`run_action`) change not at all — they are
wrapped, not rewritten.

### 9.2 Recipe B — turn your LLM service into an agent (TypeScript)

```ts
import { AIPPeer, WsClientTransport, type Message } from "@aip/protocol";

const peer = new AIPPeer("agent_001", "s_erp_001", {
  transport: new WsClientTransport("ws://gateway:8080", {
    onMessage: (m) => onMessage(m),
  }),
});

async function onMessage(m: Message) {
  const { kind, message } = peer.handle(m as any);
  if (kind !== "accept") return;

  if (message.type === "event") {
    const evt = message.payload as any;
    if (evt.name === "order.requires_review") {
      const { total } = await fetchContext(evt.data.context, ["total"]);
      if (total < 1000) {
        peer.sendAction("erp.order.approve", { target: "A12345" },
                        { in_reply_to: message.id });
      }
    }
  }
}

async function fetchContext(ref: string, fields: string[]) {
  const action = peer.sendAction("context.get", { params: { ref, fields } });
  return await waitTerminalResult(action.id);  // ignore accepted/running
}
```

### 9.3 Recipe C — minimal LLM decision wrapper

```
prompt := system + "Event: " + json(event.payload)
        + "\nAvailable actions: " + json(event.payload.data.available_actions)
reply  := LLM(json_mode=True) → validate JSON → peer.send_action(...)
```

- Validate the model's action name against the registry before sending
- Fall back to rules/small model when the large model is uncertain (§5.5)

### 9.4 Recipe D — synchronous-looking usage over the async core

The protocol is asynchronous (SPEC C.10); synchronous *experience* is a
correlation special case: send an action, wait for its terminal result.
This façade pattern gives callers a blocking API without changing the
protocol:

```python
import asyncio
from aip import AIPPeer, TERMINAL_STATUS

class SyncFacade:
    """async transport, sync-looking API (SDK helper pattern, SPEC C.10)."""
    def __init__(self, peer: AIPPeer):
        self.peer = peer
        self._pending = {}                       # action_id -> Future

    async def run_action(self, name, *, target=None, params=None, timeout=30):
        action = self.peer.build_action(name, target=target, params=params)
        fut = asyncio.get_running_loop().create_future()
        self._pending[action.id] = fut
        self.peer.send(action)                   # may re-enter on_message!
        return await asyncio.wait_for(fut, timeout)

    def on_message(self, raw: dict):
        kind, msg = self.peer.handle(raw)
        if kind != "accept" or msg.type != "result":
            return
        fut = self._pending.get(msg.in_reply_to)
        if fut is None:
            return
        if msg.payload["status"] in TERMINAL_STATUS:   # accepted/running keep waiting
            self._pending.pop(msg.in_reply_to, None)
            fut.set_result(msg.payload)
```

Notes:
- Non-terminal results (`accepted`/`running`) keep the caller waiting —
  this is exactly how synchronous semantics project onto the async core
- `build_action` before `send` so correlation exists before any
  re-entrant reply (§10 pitfall #1)
- Same pattern in TS (`waitTerminalResult`); a gateway HTTP façade
  (request/response binding) is a future profile (SPEC §9.7)

---

## 10. Common Pitfalls

All items below come from real bugs found while building the reference
implementation:

| # | Pitfall | Correct approach |
|---|---------|------------------|
| 1 | **Synchronous re-entrancy**: `send_action` triggers the peer's reply *before* your correlation state is assigned | `build_action` → register correlation → `send` (`AIPPeer.build_action`) |
| 2 | Consuming `accepted`/`running` as business results | terminal-only consumption |
| 3 | Hand-built messages without `seq` (0) | explicit seq or let `AIPPeer` assign |
| 4 | Shipping the whole DOM/screenshot/chat history in `event.data` | minimal state + `context` reference |
| 5 | Events carrying `in_reply_to` | events never carry it (I4) |
| 6 | Credentials in payloads | forbidden (I10); use application-level secure mechanisms |
| 7 | `result` without `in_reply_to` | results must reference the action id |
| 8 | Using `error` for business failure | `result.failed` + lowercase executor code |
| 9 | Actions carrying `idempotency`/`risk` | Registry/policy properties — never per-call |
| 10 | Assuming a disconnect loses the task | connection ≠ session; hello + cursors resume |
| 11 | Emitting raw telemetry events (mouse moves, DOM mutations) | semantic events only; coalesce |
| 12 | Guessing `retryable` from an error code | trust `retry.allowed` declared by the failing side |
| 13 | Duplicate action id without stored outcome reply | always return the recorded terminal outcome |
| 14 | Sending results after a terminal result for the same action | I6 — no results after terminal |

---

## 11. Testing Your Integration

### 11.1 Use the conformance fixtures as your contract tests

`conformance/tests/*.json` is language-agnostic:

- **Schema tests** — runnable by any implementation in any language
  against `schema/aip.json` (Python: `python3 conformance/run.py`;
  TypeScript: `npm test` in `sdk/typescript`)
- **Behavior tests** — declarative scenarios (`send` steps + `expect`
  assertions) that the reference harness drives against the reference
  gateway. Adapt them to *your* implementation with a minimal harness:

```python
def run_fixture(test):
    gateway = YourGateway(...)                       # your executor/gateway
    for step in test["steps"]:
        if "send" in step:
            gateway.receive(side_of(step["send"]), step["send"])
    return assert_against(test["expect"], gateway)   # see conformance/harness.py
```

### 11.2 Template replacement (fastest path)

1. Copy `examples/hello-rpa/`
2. Keep the gateway and the rule agent
3. Replace the fake `_execute` branches in `executor.py` with your real
   automation
4. Run `run.py` — the message log prints every hop; the first green run
   is your minimal integration

### 11.3 Manual debugging

- WebSocket carries plain JSON: any ws client (websocat, browser
  console) can inject frames by hand
- Malicious frames (two objects in one frame, non-JSON) are rejected at
  the frame layer — good for verifying your transport wiring (E5)

---

## 12. Error Handling Reference

Kernel error codes (10) — `error` messages only. Business failures belong
on `result.failed` with executor-defined codes.

| Code | Meaning | Executor should | Agent should |
|------|---------|-----------------|--------------|
| `INVALID_MESSAGE` | malformed envelope/type/payload | log; do not execute | log; do not send further malformed actions |
| `INVALID_ACTION` | unknown action name or bad params | check registry | fix the action (name/params) |
| `UNSUPPORTED_VERSION` | `v` not supported | upgrade or reject session | upgrade or reject session |
| `UNAUTHORIZED` | source not authenticated | check handshake/principal binding (I9) | check credentials/token |
| `SEQ_OUT_OF_ORDER` | stale or gapped sequence | fix sender seq; resume from cursor | fix sender seq; resume from cursor |
| `DUPLICATE_MESSAGE` | informational duplicate | ignore (already handled) | ignore |
| `SESSION_EXPIRED` | session TTL passed | reconnect + hello/resume | reconnect + hello/resume |
| `AGENT_UNAVAILABLE` | decision engine down | wait; retry per `retry.allowed` | n/a |
| `RPA_UNAVAILABLE` | executor down | n/a | wait; retry per `retry.allowed` |
| `INTERNAL_ERROR` | unspecified | log with context | log; treat as non-retryable unless declared |

Extension codes (profiles, lowercase): `context.not_found`,
`context.expired` — returned as `result.failed` codes by the executor.

---

## 13. FAQ

**Q: Is AIP synchronous or asynchronous?**
The **core is asynchronous** (SPEC C.10): events are unsolicited, one
action yields a *stream* of results (accepted/running → terminal), and
the loop is event-driven — because RPA/automation is dominated by
waiting on the external world. Synchronous *experience* is a correlation
special case: `in_reply_to` + wait for the terminal result (Recipe D in
§9.4). Sync-facing façades (SDK helpers, a future HTTP request/response
binding) live in the surface layers, never in the core — dual-mode
semantics would double every state machine and error path.

**Q: Why not JSON-RPC (like MCP/A2A)?**
AIP is not request/response: `event` is unsolicited, and one `action`
yields a *stream* of results (accepted → running → ok). JSON-RPC also
has no per-stream ordering, dedup, cursors, or resume — AIP would layer
them on as an overlay anyway. A JSON-RPC *binding* could later be a
profile without changing semantics (SPEC C.3).

**Q: Is the gateway required?**
No. Peer-to-peer agent ↔ executor is valid (SPEC §2). The gateway adds
policy, retry, resume, and audit — recommended in production, optional
everywhere.

**Q: How is AIP different from MCP / A2A?**
MCP answers "what can I do?" (AI → capability). A2A answers "how do
agents cooperate?" (agent ↔ agent). AIP answers "what should happen
next?" (decision engine ↔ executor) — a narrower boundary optimized for
high-frequency, low-context, state-driven interaction (SPEC Appendix B).
AIP does not replace MCP or A2A; an AIP action may route through an MCP
capability gateway (SPEC §9.5).

**Q: Can I use HTTP instead of WebSocket?**
v0.1 standardizes only WebSocket. HTTP, QUIC, binary encodings are future
profiles (SPEC §9.7); anything you build must preserve Kernel semantics.

**Q: How do I add a new capability?**
Register a new action in your Action Registry (name, params, idempotency,
timeout, risk). Never add a message type.

**Q: My action may be unsafe to repeat. What do I do?**
Declare `idempotency: none` in the registry. The gateway will never
retry it after execution may have started, and duplicates are blocked by
`executed_action_ids`.

**Q: The executor and agent are in the same process. Do I need a socket?**
No — use the in-memory transport (`Endpoint`/`Wire`). Everything above
applies unchanged.

**Q: Can multiple agents share one session?**
Yes — each sender keeps its own `(session, source)` stream (I7); cursors
and resume are per stream.

**Q: How do I handle very high event rates?**
Coalesce into semantic events (one per business state change). AIP has
no flow control in v0.1; backpressure is roadmap (SPEC §15.1).

**Q: How is the protocol versioned?**
Kernel additions require a demonstrated interoperability/correctness
failure that extensions cannot solve (Complexity Budget, SPEC §9.1).
Extensions are ratified independently as profiles.

---

## 14. Integration Checklist

**Executor**
- [ ] All events are semantic (no telemetry/DOM/screenshots)
- [ ] Events carry minimal state; large objects via `context` references
- [ ] Every inbound message goes through `handle()`; only `accept` processed
- [ ] `accepted` replied first (long tasks); exactly one terminal result
- [ ] `executed_action_ids` maintained; duplicates return `duplicate:true`
      + `original_result_id`
- [ ] Business failure → `result.failed` + lowercase code; `error` only
      for protocol anomalies
- [ ] Own stream `seq` contiguous (use `AIPPeer`)
- [ ] `source` matches authenticated principal; no credentials in payloads
- [ ] Registry declared (idempotency/timeout/retries per action)

**Agent**
- [ ] Terminal results only; `accepted`/`running` never trigger business
- [ ] Data fetched via `context.get` on demand
- [ ] Actions carry only `name/target/params/expect`
- [ ] `rejected` → stop or escalate; no forcing
- [ ] Retry only on `retry.allowed`, reusing the same action id
- [ ] Decision engine replaceable (rules/small/LLM) — protocol-agnostic

**Both**
- [ ] Reconnect via hello + cursors; action state survives (I3)
- [ ] Heartbeats don't consume application seq
- [ ] Production uses a gateway for policy/audit (AI output is untrusted)

---

## 15. Glossary

| Term | Definition |
|------|------------|
| **Decision Engine (Agent)** | consumes events, produces actions; rule/small/LLM/human |
| **Executor (RPA)** | executes actions, emits events; your automation |
| **Gateway** | optional mediator: policy, retry, resume, audit, ordering |
| **Session** | execution context with externalized state; outlives connections |
| **Stream** | ordered sequence of one sender in one session: `(session, source)` |
| **Participant** | a party identified by `source`, bound to an authenticated principal |
| **Cursor** | a receiver's last applied seq per stream; the resume unit |
| **Terminal result** | `ok`/`failed`/`timeout`/`rejected` — ends the action |
| **Context ref** | addressable, versioned, expiring object behind a reference |
| **Semantic event** | a business state change; never raw telemetry |

---

## 16. Appendix

### 16.1 Action lifecycle

```
PENDING → ACCEPTED → RUNNING → SUCCESS
                    └──> FAILED | TIMEOUT | REJECTED
```

No results after a terminal result (I6).

### 16.2 Invariants (SPEC §8.1)

```
I1   an action's execution identity is (session, action.id)
I2   a duplicate action id must not cause a second execution
I3   a connection failure must not change execution state
I4   an event is observational, never imperative
I5   an action is imperative, never observational
I6   a terminal result must not transition back to executing
I7   ordering applies only within the (session, source) stream
I8   protocol timestamps must not establish ordering
I9   never trust `source` without transport-level authentication
I10  credentials never appear in ordinary message payloads
```

### 16.3 File index

| File | Purpose |
|---|---|
| `SPEC.md` | normative Kernel v0.1 spec |
| `schema/aip.json` | authoritative JSON Schema for envelope + 4 messages |
| `conformance/tests/` | contract fixtures (schema + behavior) |
| `examples/hello-rpa/` | runnable three-party integration (executor/agent/gateway) |
| `sdk/python/`, `sdk/typescript/` | SDKs: messages/seq/session/transports/ContextStore |
| `benchmarks/` | cost benchmark (context-reduction mechanism) |
