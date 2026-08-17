# AIP — AI Interaction Protocol

**Specification v0.1 (Kernel)**

> AIP is a minimal protocol for reliable, state-driven interaction between
> a decision engine and an executor. Its primary optimization target is
> **minimum sufficient context per decision**, not minimum message size.

**Status:** Draft · **Scope:** Kernel (minimal implementable core) · **Binding:** WebSocket (only) · **License:** MIT

---

## Table of Contents

1. [Scope](#1-scope)
2. [Terminology](#2-terminology)
3. [Wire Model](#3-wire-model)
4. [Four Messages](#4-four-messages)
5. [Correlation & Ordering](#5-correlation--ordering)
6. [Action Lifecycle](#6-action-lifecycle)
7. [Delivery & Resume](#7-delivery--resume)
8. [Invariants & Security](#8-invariants--security)
9. [Extensions](#9-extensions)
10. [Conformance](#10-conformance)

Appendices: [A. End-to-end example](#a-end-to-end-example) ·
[B. Ecosystem positioning](#b-ecosystem-positioning) ·
[C. Design decisions](#c-design-decisions) ·
[D. Repository layout](#d-repository-layout) ·
[E. Benchmark protocol](#e-benchmark-protocol)

---

## 1. Scope

### 1.1 What AIP is

AIP is an **event-driven, low-context, reliable communication protocol**
between an **AI decision engine** and an **executor** (RPA, browser
automation, ERP, IoT, API agents, or another agent).

It turns an LLM from a *long-context chat endpoint* into a *decision node*:
it receives a minimal event/state packet, produces one decision, and
returns it as a short, structured message.

The protocol defines only how these components exchange **minimal,
reliable, verifiable** state and actions. Everything else is pushed into
extensions or profiles (§9).

### 1.2 What AIP is not

AIP is **not**:

- a replacement for MCP (capability protocol)
- a replacement for A2A (agent-to-agent protocol)
- a workflow engine, an agent platform, or a chat protocol
- an LLM memory / context-management framework
- a tool-discovery or prompt-management mechanism
- a definition of the executor itself

### 1.3 How AIP relates to MCP and A2A

A2A (now at 1.0) standardizes agent-to-agent interoperation: tasks,
messages, artifacts, streaming, and asynchronous operations.
MCP standardizes capability connection: tools, resources, sampling,
elicitation, cancellation, progress, and — in recent revisions — Tasks
for persistent execution state.

AIP does **not** claim those protocols lack state or real-time ability.
AIP instead defines a **narrower execution-runtime abstraction**:

> AIP is optimized for **high-frequency, low-context, state-driven
> interaction across the decision-engine ↔ executor boundary**, with
> explicit per-stream ordering, idempotent action execution, and
> resumable delivery.

It complements MCP and A2A rather than replacing them. An AIP action
may be routed through an MCP capability gateway (§9.5), and an AIP
session may be created inside an A2A-managed task (§9.6).

### 1.4 Explicitly out of scope

| Area | Delegated to |
|------|--------------|
| Agent discovery / agent cards | A2A, agent frameworks |
| Tool discovery / tool schemas | MCP |
| Prompt management, model selection, temperature, CoT, token budgets | Agent implementation |
| LLM memory / context management | Agent implementation |
| File transfer / large artifacts | Application layer |
| Long-running task orchestration | Workflow engines, A2A |
| Agent-to-agent collaboration | A2A |
| The executor itself (browser, OS, ERP internals) | Implementers |

> **Rule:** if a capability already has a mature standard or solution,
> AIP must not re-invent it.

---

## 2. Terminology

| Term | Definition |
|------|------------|
| **Decision Engine** (Agent) | The party that consumes `event`s and produces `action`s. May be a rule engine, a small model, an LLM, a human, or another agent. AIP never assumes which. |
| **Executor** (RPA) | The party that executes `action`s and emits `event`s. Browser automation, desktop RPA, ERP, IoT device, API adapter, etc. |
| **Gateway** | **Optional** intermediary between decision engine and executor. Holds session state, applies policy, orders streams, retries. AIP MUST work peer-to-peer without a gateway. |
| **Session** | An execution context with externalized state. A session is **state, not chat history**. Sessions outlive connections. |
| **Stream** | The ordered message sequence of one sender within one session, identified by `(session, source)`. |
| **Participant** | A protocol party identified by `source`, bound to an authenticated principal at the transport layer. |
| **Cursor** | The last **applied** sequence number of a stream, per receiver. The unit of resume (§7.4). |

### 2.1 The core loop

AIP's entire execution model is one loop:

```
EVENT
  ↓
DECISION      (inside the decision engine; never a wire message)
  ↓
ACTION
  ↓
RESULT
  ↓
EVENT ...
```

```
E → D → A → R
```

- **Event** — a fact that has happened.
- **Decision** — internal to the decision engine.
- **Action** — a request to the executor.
- **Result** — the objective outcome of that action.

### 2.2 The three iron laws

1. **Small Core.** The Kernel must be readable end-to-end by one engineer
   in half a day.
2. **Semantic, not verbose.** Transmit business semantics, not UI noise,
   DOM dumps, chat history, or model internals.
3. **Protocol, not Platform.** AIP is not an agent platform; it is a
   thin wire contract. Extensions exist (§9), but the core never grows
   by accretion.

---

## 3. Wire Model

### 3.1 The AIP Kernel is a semantic core

```
┌──────────────────────────────────┐
│        AIP Semantic Core         │
│  envelope · 4 messages · stream  │
│  ordering · action lifecycle     │
│  cursors · invariants            │
└──────────────┬───────────────────┘
               │
      ┌────────┴────────┐
      │  WebSocket      │   ← the only binding in v0.1
      │  Binding        │
      └─────────────────┘
```

**v0.1 standardizes exactly one binding: JSON messages over WebSocket
(text frames, UTF-8, one message per frame).** No other binding is
standardized in the Kernel. HTTP, QUIC, Unix socket, MQTT, and binary
encodings (MessagePack, CBOR, Protobuf) are future profiles (§9.7) that
MUST NOT alter the semantic core.

Rationale: transport semantics (ordering, resume, timeout, heartbeat)
are themselves a large design surface. Maintaining one binding keeps the
Kernel implementable; adding a second binding is a ratified amendment.

### 3.2 Envelope

All four message types share one envelope:

```json
{
  "v": 1,
  "type": "event",
  "id": "evt_123",
  "in_reply_to": null,
  "session": "s_001",
  "seq": 100,
  "ts": 1786944500123,
  "source": "rpa_001",
  "payload": {}
}
```

| Field | Required | Meaning |
|-------|----------|---------|
| `v` | yes | Protocol version. Kernel v0.1 = `1`. |
| `type` | yes | `event` \| `action` \| `result` \| `error` (exactly these four; anything else is `INVALID_MESSAGE`). |
| `id` | yes | Message ID, unique within its stream `(session, source)` at minimum; SHOULD be a ULID/UUID for cross-system correlation (§5.2). |
| `in_reply_to` | no | ID of the message this message answers (§5.3). |
| `session` | yes | Session identifier (§7.2). |
| `seq` | yes | Monotonically increasing sequence within the `(session, source)` stream (§5.4). |
| `ts` | yes | Epoch milliseconds. **Informational only.** MUST NOT be used for ordering or timeout correctness (§5.5). |
| `source` | yes | Participant identity of the sender; MUST be bound to an authenticated principal (§8.4). |
| `payload` | yes | Message body; shape depends on `type`. |

### 3.3 Envelope is deliberately not JSON-RPC

MCP and A2A use JSON-RPC 2.0. AIP does not, for reasons documented in
[C.3](#c3-why-not-json-rpc). A JSON-RPC binding may later be offered as
a profile without changing the semantic core.

---

## 4. Four Messages

The Kernel defines **exactly four** envelope message types. There is no
fifth type in v0.1. (Context access, approval, etc. are **actions**, not
message types — §9.)

| Type | Meaning | Direction |
|------|---------|-----------|
| `event` | A fact that has happened | Executor → Decision Engine |
| `action` | A request to execute something | Decision Engine → Executor |
| `result` | The outcome(s) of an action | Executor → Decision Engine |
| `error` | A protocol / transport / processing anomaly | either |

**Strict semantics — do not blur these:**

- An `event` is **observational, never imperative** (I4). It states what
  happened; it never asks for anything.
- An `action` is **imperative, never observational** (I5). It requests
  execution; it never reports a fact or explains a reason.
- A `result` states **what actually happened** after an action.
- An `error` reports an anomaly in the protocol/transport/processing
  layer — not a business outcome. Business-level failures are
  `result.status = failed` (§4.6, §6).

### 4.1 event

```json
{
  "v": 1,
  "type": "event",
  "id": "evt_123",
  "session": "s_001",
  "seq": 100,
  "ts": 1786944500123,
  "source": "rpa_001",
  "payload": {
    "name": "button.appeared",
    "data": {
      "id": "confirm",
      "text": "Confirm order",
      "enabled": true
    }
  }
}
```

- `payload.name`: **semantic** event name (dot-namespaced). Events are
  business-relevant state changes, never raw telemetry (mouse moves, DOM
  mutations, screenshots).
- `payload.data`: the **minimum** state required to decide. If the full
  state is large, send a reference instead (§9.2).

### 4.2 action

```json
{
  "v": 1,
  "type": "action",
  "id": "act_123",
  "in_reply_to": "evt_123",
  "session": "s_001",
  "seq": 51,
  "ts": 1786944500123,
  "source": "agent_001",
  "payload": {
    "name": "browser.click",
    "target": "confirm",
    "params": {},
    "expect": {
      "event": "page.changed"
    }
  }
}
```

- `payload.name`: the action name — a **named capability invocation**
  (`browser.click`, `erp.order.approve`). The Kernel defines **zero**
  actions; names come from the Action Registry profile (§9.3).
- `payload.target`: reference to an entity from an earlier event's `data`.
- `payload.params`: action parameters, validated against the registry.
- `payload.expect` (optional): the decision engine's assertion of what
  should follow if the action succeeds (e.g. event name). **The Kernel
  defines only the reference; matching semantics are an extension**
  (§9.8).
- Actions do **not** carry `idempotency` or risk metadata: those are
  Registry/policy properties, never per-call parameters (§9.3, §9.4).

### 4.3 result

An action MAY produce **multiple** `result` messages (§6.2):

- **non-terminal:** `accepted`, `running`
- **terminal:** `ok`, `failed`, `timeout`, `rejected`

Terminal example:

```json
{
  "v": 1,
  "type": "result",
  "id": "res_123",
  "in_reply_to": "act_123",
  "session": "s_001",
  "seq": 102,
  "ts": 1786944500123,
  "source": "rpa_001",
  "payload": {
    "status": "ok",
    "data": {
      "page": "payment"
    }
  }
}
```

Non-terminal example (executor accepted and is running):

```json
{
  "v": 1,
  "type": "result",
  "id": "res_120",
  "in_reply_to": "act_123",
  "session": "s_001",
  "seq": 101,
  "source": "rpa_001",
  "payload": {
    "status": "accepted"
  }
}
```

Duplicate replay of an already-settled action (§6.4):

```json
{
  "v": 1,
  "type": "result",
  "id": "res_456",
  "in_reply_to": "act_123",
  "session": "s_001",
  "seq": 105,
  "source": "rpa_001",
  "payload": {
    "status": "ok",
    "duplicate": true,
    "original_result_id": "res_123"
  }
}
```

### 4.4 Terminal statuses

| Status | Meaning |
|--------|---------|
| `ok` | Executed successfully. |
| `failed` | Executed but failed. `payload.code` is an **executor-defined** code (e.g. `target_not_found`); MAY carry `retry: {allowed, after_ms}`. |
| `timeout` | Did not complete within its allowed window. |
| `rejected` | Refused before execution — by gateway policy, permission, or the executor itself. |

### 4.5 error

Errors are **protocol / transport / processing anomalies**:

```json
{
  "v": 1,
  "type": "error",
  "id": "err_123",
  "in_reply_to": "act_123",
  "session": "s_001",
  "seq": 102,
  "source": "rpa_001",
  "payload": {
    "code": "SEQ_OUT_OF_ORDER",
    "retry": { "allowed": false },
    "message": "stale seq 101; last applied 102"
  }
}
```

- `payload.code`: one of the Kernel error codes (§4.6).
- `payload.retry` (optional): `{allowed, after_ms}`. Retryability is
  **declared by the sender of the error, never guessed by the receiver**
  (I-decisions in §C).

### 4.6 Kernel error codes

The Kernel error registry is exhaustive for the Kernel. (Executor-level
failure codes on `result.failed` are namespaced, lower-case, and MUST
NOT collide with these; extension profiles add codes inside their own
namespace, e.g. `context.not_found`.)

| Code | Meaning |
|------|---------|
| `INVALID_MESSAGE` | Malformed envelope, unknown `type`, invalid payload shape |
| `INVALID_ACTION` | Unknown action name or invalid parameters |
| `UNSUPPORTED_VERSION` | `v` not supported |
| `UNAUTHORIZED` | Sender not authenticated / not authorized at protocol level |
| `SEQ_OUT_OF_ORDER` | Stale or gapped sequence |
| `DUPLICATE_MESSAGE` | Duplicate detected (informational) |
| `SESSION_EXPIRED` | Session closed or stale |
| `AGENT_UNAVAILABLE` | Decision engine unreachable |
| `RPA_UNAVAILABLE` | Executor unreachable |
| `INTERNAL_ERROR` | Unspecified failure |

---

## 5. Correlation & Ordering

### 5.1 Three identities, three scopes

| Identity | Uniqueness scope |
|----------|------------------|
| `session` | Unique system-wide for its lifetime (ULID/UUID). |
| `message.id` | Unique within the stream `(session, source)`; SHOULD be globally unique (ULID/UUID) for audit and cross-system correlation. |
| `action.id` | The action's logical execution identity within its session. This is the deduplication key (§6.4). |

IDs MUST be unique within their correlation and deduplication scope —
the weaker guarantee is sufficient for correctness, and ULID/UUIDs make
"global" a cheap SHOULD rather than a MUST.

### 5.2 Message IDs

- IDs are immutable. A **resent message MUST keep its original `id`**
  (this is what makes at-least-once delivery deduplicable).
- Prefixes (`evt_`, `act_`, `res_`, `err_`) are a convention, not a rule.

### 5.3 Correlation: `in_reply_to`

| Message | `in_reply_to` semantics |
|---------|-------------------------|
| `action` | MAY reference the triggering `event.id`. |
| `result` | **MUST** reference the `action.id` it answers. |
| `error` | SHOULD reference the message it failed to process. |
| `event` | MUST NOT carry `in_reply_to` (events are independent observations). |

### 5.4 Sequence: per-stream, never global

`seq` is monotonically increasing **within the `(session, source)`
scope** — one sequence per sender stream:

```
stream (s_001, rpa_001):    100  101  102  103  ...
stream (s_001, agent_001):   50   51   52   ...
```

- Two different senders in one session do **not** share a sequence.
  There is no global sequence; ordering applies only within a stream (I7).
- `seq` starts at 1 with the first message of the stream.
- The receiver MUST accept a message only if `seq == last_applied + 1`
  (or, for resent messages, `seq <= last_applied` **and** `id` already
  applied → duplicate, ignore without re-execution).
- A gap (`seq > last_applied + 1`) is reported as `SEQ_OUT_OF_ORDER` and
  the receiver continues from its cursor; it MUST NOT buffer silently.

### 5.5 Timestamps

`ts` is **informational**. Distributed wall clocks are unreliable:
ordering is established by `seq`, timeout by monotonic clocks within a
single process. `ts` MUST NOT be used for ordering or timeout
correctness (I8).

---

## 6. Action Lifecycle

### 6.1 States

The Gateway (or, without a gateway, the executor + decision engine
cooperatively) tracks each action:

```
PENDING
  ↓
ACCEPTED      (executor received and will execute)
  ↓
RUNNING       (optional)
  ↓
SUCCESS | FAILED | TIMEOUT | REJECTED
```

Transitions:

```
PENDING     → ACCEPTED | REJECTED
ACCEPTED    → RUNNING | SUCCESS | FAILED | TIMEOUT | REJECTED
RUNNING     → SUCCESS | FAILED | TIMEOUT
(terminal)  → (no further transitions — I6)
```

### 6.2 Receipt vs outcome: two-layer results

An action that executes for 30 seconds must distinguish **receipt** from
**outcome**. AIP does this with result statuses, not with new message
types:

- `accepted` and `running` are **non-terminal** progress results.
- `ok`, `failed`, `timeout`, `rejected` are **terminal** outcomes.

An action MAY produce zero or more non-terminal results and MUST
eventually produce **exactly one** terminal result — unless the protocol
itself fails (`error`), in which case recovery is governed by §6.5/§7.

Example sequence for one action:

```
action   act_123  (agent stream, seq 51)
result   accepted (rpa stream,  seq 101)
result   running  (rpa stream,  seq 102)
result   ok       (rpa stream,  seq 103)   ← terminal
```

### 6.3 Executor obligations

The executor MUST:

1. maintain `executed_action_ids` for the session;
2. **never execute** an action whose `id` it has already executed (I2);
3. when receiving a duplicate `action.id`, **return the previously
   recorded terminal outcome**, if known, with `duplicate: true` and
   `original_result_id` (§4.3) — it must never answer "unknown" for a
   settled action;
4. emit non-terminal `accepted` promptly if execution may take longer
   than the agreed timeout window;
5. refuse (terminal `rejected`) instead of half-executing when a
   precondition fails before execution.

### 6.4 Idempotency semantics

Idempotency is a property of the **action definition** (Registry), not
of the action message, and never a per-call LLM parameter. Overrides are
possible only through explicit policy (§9.4).

| Class | Meaning | Retry on timeout/transport loss |
|-------|---------|----------------------------------|
| `required` | MUST be safe to re-execute with the same `id`; duplicate MUST return the stored outcome | Allowed |
| `optional` | SHOULD be idempotent; dedup by `id` when possible | Allowed |
| `none` | Re-execution is unsafe (e.g. `browser.click`, `bank.transfer`) | Forbidden once execution may have started |

### 6.5 Retry

- Retry is initiated by the **Gateway** (or, peer-to-peer, by the
  decision engine under policy), never by the receiver.
- Retry MAY occur when: `error` with `retry.allowed: true`; transport
  failure before `accepted`; timeout with `idempotency != none`.
- A retry MUST reuse the same `action.id`. The executor deduplicates
  (I2) and returns the stored outcome (§6.3-3).

The "at-least-once transport + idempotent-when-possible actions +
stored-outcome-on-duplicate" combination is AIP's pragmatic answer to
exactly-once: **duplicates must never cause duplicate dangerous actions,
and must never hide an already-known outcome.**

---

## 7. Delivery & Resume

### 7.1 Delivery semantics

- **Transport: at-least-once.** Duplicates are expected and handled by
  `id`/`seq` deduplication.
- **State: connection-independent.** A connection failure MUST NOT
  change execution state (I3).
- **Session ≠ connection.** A session persists across connections and
  outlives them.

### 7.2 Session

A session is an identifier plus externalized state stored by the
Gateway/executor (or both) — never by the decision engine's context:

```
session: s_001
task:   submit_order
state:  checkout
vars:   { order_id: "A12345" }
```

Session lifecycle (minimal, informational; full task lifecycle belongs
to A2A/workflow engines):

```
ACTIVE → COMPLETED | FAILED | CANCELLED | SUSPENDED
```

`SESSION_EXPIRED` is reported for messages on an expired session.

### 7.3 Heartbeat

Heartbeat is a **binding-level** concern and MUST NOT consume application
`seq`:

```
→ { "ping": { "session": "s_001" } }
← { "pong": { "session": "s_001" } }
```

A missed heartbeat marks the connection dead; recovery proceeds via
resume (§7.4). Pings may carry no timestamps; monotonic local clocks
govern liveness.

### 7.4 Cursors and resume

Each receiver tracks, per stream, its **cursor**: the last *applied*
sequence number.

```
cursor (s_001, rpa_001)   = 102    (applied by decision engine / gateway)
cursor (s_001, agent_001) =  51    (applied by executor / gateway)
```

On (re)connect, the WebSocket binding handshake carries the peer's
cursors (binding-level `hello`, not an application message):

```json
{
  "hello": {
    "session": "s_001",
    "cursors": {
      "rpa_001": 102,
      "agent_001": 51
    }
  }
}
```

The sender resumes from `cursor + 1`. Resent messages keep their
original `id` and `seq`, so duplicates are discarded and settled actions
return stored outcomes (§6.3-3). **Resume answers the question "who
knows how far execution got?" with per-stream cursors, not a single
number.**

---

## 8. Invariants & Security

### 8.1 Protocol invariants

These invariants are normative. They are worth more than any feature:

| # | Invariant |
|---|-----------|
| I1 | Every action has exactly one logical execution identity: `(session, action.id)`. |
| I2 | A duplicate action id MUST NOT cause a second execution. |
| I3 | A connection failure MUST NOT change execution state. |
| I4 | An event is observational, never imperative. |
| I5 | An action is imperative, never observational. |
| I6 | A terminal result MUST NOT transition back to executing; after a terminal result, no further result messages may be produced for that action. |
| I7 | Sequence ordering applies only within the `(session, source)` stream. |
| I8 | Protocol timestamps MUST NOT establish ordering or timeout. |
| I9 | An executor MUST NOT trust `source` without transport-level authentication. |
| I10 | Credentials, tokens, cookies, and other secrets MUST NOT be transmitted in ordinary event/action/result/error payloads unless protected by an application-specific secure mechanism. |

### 8.2 The security invariant

> **Decision-engine output is untrusted input. The AI never holds final
> execution authority.**

```
                AI
                 │
              Action
                 ↓
          ┌─────────────┐
          │ Gateway /   │   validation & policy
          │ Executor    │
          └──────┬──────┘
                 ↓
              Execution
```

### 8.3 Pre-execution validation

Before execution, the receiving side MUST check:

1. Is `source` authenticated and bound to a principal (§8.4)?
2. Is the session valid and owned by that principal (§8.5)?
3. Does the action exist in the registry and are `params` valid?
4. Is the action permitted for this principal (authorization)?
5. Does the current session state allow this action (ordering)?
6. Does policy require human approval or does risk metadata forbid it
   (§9.4)?

Any violation yields terminal `result.status = rejected` (or `error`
for protocol-level problems), **before** execution — never after.

### 8.4 Authentication and source binding

- Transport MUST be TLS 1.2+ for any network deployment.
- v0.1 recommended authentication: Bearer tokens / OAuth 2.0; mTLS is
  permitted. The handshake binds `source` → authenticated principal →
  session capabilities.
- `source` is a **participant identity**, not free-form text. A message
  whose `source` does not match the authenticated principal is rejected.

### 8.5 Replay and tenant isolation

- Replay protection: messages with `seq <= last_applied` for that stream
  are duplicates by construction; sessions carry short TTLs; resumption
  is governed by cursors, never by replayed messages.
- Multi-tenant isolation: a session MUST NOT cross tenant boundaries.
  The Gateway MUST scope session lookup and action authorization by the
  authenticated principal.
- Audit: every action is logged with `id`, `source`, `verdict`,
  `timestamp`, and outcome; audit logs are append-only.

---

## 9. Extensions

Everything below is **not** part of the Kernel. Extensions are organized
as **profiles**: optional, self-contained, and ratified independently.

### 9.1 Complexity budget (governance)

Feature creep is the protocol's #1 enemy. The Kernel operates under a
**complexity budget**, recorded for transparency rather than as sacred
caps:

| Dimension | Kernel v0.1 |
|-----------|-------------|
| Message types | **4** |
| Envelope fields | **9** (7 required) |
| Kernel actions | **0** (action names live in registries) |
| Action states | **6** |
| Terminal result statuses | **4** |
| Kernel error codes | **10** |
| Bindings | **1** |

> **Any addition to the Kernel requires a demonstrated interoperability
> or correctness failure that cannot be solved as an extension or
> profile.** Numbers may change only by ratified amendment — and the
> amendment must cite the failure.

### 9.2 Context-on-Demand (profile)

The token-cost killer, defined **without new message types**:
context access is an **action** (`context.get`) answered by a `result`.

```
event: order.requires_review, data: { context: "ctx_8392" }
```

```json
{
  "v": 1, "type": "action",
  "id": "act_002",
  "in_reply_to": "evt_124",
  "session": "s_001", "seq": 52, "source": "agent_001",
  "payload": {
    "name": "context.get",
    "params": {
      "ref": "ctx_8392",
      "fields": ["order.total", "order.customer", "order.status"]
    }
  }
}
```

```json
{
  "v": 1, "type": "result",
  "id": "res_130",
  "in_reply_to": "act_002",
  "session": "s_001", "seq": 104, "source": "rpa_001",
  "payload": {
    "status": "ok",
    "data": {
      "ref": "ctx_8392",
      "data": {
        "order.total": 299,
        "order.customer": "customer_001",
        "order.status": "pending"
      }
    }
  }
}
```

Profile rules:

- Context objects are addressable, versioned, and expire
  (extension codes `context.not_found`, `context.expired`).
- The Gateway/executor owns context storage; consumers fetch **only the
  fields they need**.
- Events carry references, never bulk payloads, when data is large.

The optimization target is **minimum sufficient context** — never
"minimum bytes" at the cost of decision accuracy (see Appendix E).

### 9.3 Action Registry (profile)

**The Kernel defines zero actions.** An action is a *named capability
invocation*; names live in executor-defined registries:

```
browser.click        browser.input       browser.navigate
erp.order.approve    erp.order.reject    slack.notify
database.query       ...
```

A registry entry defines: `name`, `params` schema, `idempotency`
(§6.4), risk metadata (§9.4), and an optional `expect` template:

```json
{
  "name": "browser.click",
  "params": { "target": { "type": "string" } },
  "idempotency": "none",
  "risk": { "class": "ui" }
}
```

**Action semantics are defined by the Registry, never by the caller.**
No action message may carry `idempotency` or risk overrides (§4.2);
overrides require explicit policy.

### 9.4 Policy & risk metadata (profile)

Risk classification is business-specific; the Kernel only knows that
actions carry opaque policy metadata. Profiles MAY define taxonomies
(such as the earlier `L0–L4` sketch) — but a deployment decides, not the
protocol:

```json
{
  "policy": {
    "max_risk": "L2",
    "require_approval": ["erp.order.approve"],
    "allowed_domains": ["example.com"]
  }
}
```

Policy violations yield `result.status = rejected` at the gateway,
before execution. Human approval is a profile (WAITING / SUSPENDED
session states).

### 9.5 MCP integration (profile)

AIP actions MAY be routed through an MCP capability gateway:

```
              Decision Engine
                    │
                 AIP action
                    │
                 Gateway
                    │
                 MCP tool
                    │
                 Executor
```

**AIP = runtime protocol (what should happen next). MCP = capability
protocol (what can I do).** The two do not compete; one routes, the
other executes.

### 9.6 A2A integration (profile)

An AIP session may be created inside an A2A task: the A2A layer owns
agent-level task lifecycle; AIP owns the decision-engine ↔ executor
boundary inside it.

### 9.7 Bindings & encodings (profile)

Future profiles: HTTP binding, MessagePack/CBOR/Protobuf encodings,
QUIC, Unix sockets, MQTT. All MUST preserve Kernel semantics; conformance
runs against the semantic core.

### 9.8 Expect matching (profile)

The Kernel defines `expect` as a bare reference (an event name the
decision engine asserts should follow). Matching semantics — timeouts,
predicates over event data, "within N ms" — are profile material. This
keeps the core small while keeping actions verifiable.

### 9.9 Decision routing (profile)

The decision engine is a routing target, never a wire message type.
Profiles MAY cascade:

```
Event → Rule Engine (deterministic, no model call)
      → Small Model (cheap)
      → Large LLM   (expensive)
```

Zero-LLM executions are first-class. Semantic events (business state
changes, not telemetry) are the executor/adapter's responsibility;
profiles SHOULD define event-name taxonomies to prevent event storms.

---

## 10. Conformance

A protocol is real only when implementations can be verified. The
conformance suite tests the Kernel against the invariants (§8.1) and
message semantics (§4–§7). Passing implementations earn:

```
AIP/1.0 Conformant
```

### 10.1 Test groups

**Envelope & wire (E)**
- [ ] E1: message with all required fields parses
- [ ] E2: unknown `type` → `INVALID_MESSAGE`
- [ ] E3: unsupported `v` → `UNSUPPORTED_VERSION`
- [ ] E4: missing required field → `INVALID_MESSAGE`
- [ ] E5: one JSON message per frame; UTF-8

**Messages (M)**
- [ ] M1: `event` payload shape valid; `in_reply_to` absent
- [ ] M2: `action` carries `name`/`target`/`params`; no `idempotency` field present (Registry-owned)
- [ ] M3: `result` MUST reference an `action.id`; absent → `INVALID_MESSAGE`
- [ ] M4: terminal statuses are exactly `ok|failed|timeout|rejected`
- [ ] M5: `error` codes restricted to the Kernel registry; unknown code → `INVALID_MESSAGE`

**Sequence & ordering (S)**
- [ ] S1: per-stream `(session, source)` seq accepted in order
- [ ] S2: duplicate `seq` + `id` → ignored (duplicate), no side effect
- [ ] S3: stale `seq` → `SEQ_OUT_OF_ORDER` (or duplicate per S2)
- [ ] S4: gap → `SEQ_OUT_OF_ORDER`; no silent buffering
- [ ] S5: two senders in one session keep independent sequences (I7)

**Action lifecycle (A)**
- [ ] A1: `accepted` → `running` → `ok` valid
- [ ] A2: terminal followed by another result → rejected (I6)
- [ ] A3: duplicate action id after `ok` → stored outcome with `duplicate: true`, `original_result_id`
- [ ] A4: duplicate action id for `idempotency: none` → stored outcome, **no second execution**
- [ ] A5: timeout for `idempotency: none` → no retry
- [ ] A6: retry of `idempotency: required` reuses `action.id`

**Delivery & resume (D)**
- [ ] D1: `hello` handshake carries per-stream cursors
- [ ] D2: resume re-sends from `cursor + 1` with original `id`/`seq`
- [ ] D3: after resume, settled actions return stored outcomes, not re-execution
- [ ] D4: heartbeat does not advance application `seq`
- [ ] D5: connection drop mid-action → action state unchanged (I3)

**Security (K)**
- [ ] K1: `source` mismatch with authenticated principal → rejected
- [ ] K2: action on expired session → `SESSION_EXPIRED`
- [ ] K3: payload scanning: no credential patterns in ordinary messages (I10)
- [ ] K4: policy violation → terminal `rejected`, never executed
- [ ] K5: `ts` used for ordering → conformance failure (I8, static check)

Conformance does **not** test model quality, decision accuracy, or cost;
those belong to benchmarks (Appendix E).

---

## Appendices

### A. End-to-end example

`submit_order` across two streams (seqs are per-sender):

```
rpa_001  (stream)           gateway               agent_001 (stream)
───────  ────────            ───────               ────────  ────────
seq 100  event page.changed →                      │
         {page: checkout,                          │
          elements:[{id:confirm}]}                 │
                                                   │  decides
                                    ← action       │  seq 51
                                    browser.click  │  {target:confirm,
                                    seq 100 →      │   expect:{event:
                                    │              │   page.changed}}
seq 101  result accepted →
seq 102  result running  →
seq 103  result ok → (data:{page:payment}) →       │
seq 104  event page.changed {page:payment} →       │  decides
                                    ← action       │  seq 52
                                    erp.order.approve (idempotency
                                    seq 101 →      │  required, policy-
                                    │              │  approved)
seq 105  result ok (duplicate-safe) →
```

There is no `user:… / AI:…` exchange anywhere. The loop is:
`STATE → EVENT → DECISION → ACTION → RESULT → STATE`.

### B. Ecosystem positioning

| | **MCP** | **A2A** | **AIP** |
|--|---------|---------|---------|
| Core | Capability protocol | Agent interop protocol | Executor-runtime protocol |
| Question | What can I do? | How do agents cooperate? | What should happen next? |
| Unit | Tool / Resource | Task / Message | Event ↔ Action |
| Boundary | AI ↔ tools | agent ↔ agent | decision engine ↔ executor |
| State | Tasks (recent revisions); otherwise tool-call-centric | Task lifecycle, streaming | Action lifecycle + per-stream cursors |
| Ordering/recovery | Transport-defined (stdio, streamable HTTP) | Task-based | Per-stream seq, cursors, resume |
| Context efficiency | Not a primary goal | Not a primary goal | **Primary optimization target** |

AIP is not a competitor to MCP or A2A. It defines a narrower
execution-boundary abstraction optimized for high-frequency, low-context,
state-driven interaction — a boundary MCP and A2A do not specifically
optimize.

### C. Design decisions

#### C.1 Four messages only

The E→D→A→R loop needs nothing more. Anything else (context, approval,
progress) is expressed as **actions and results**, keeping
`Message Types = 4` and `Action Types = N`.

#### C.2 Two-layer results

Receipt (`accepted`/`running`) and outcome (`ok`/`failed`/`timeout`/
`rejected`) must be distinguishable for long-running actions. Multiple
result messages per action express this without new message types, and
I6 bounds them.

#### C.3 Why not JSON-RPC?

MCP and A2A use JSON-RPC 2.0; AIP deliberately does not:

1. AIP is not request/response: `event` is an unsolicited observation,
   and one `action` yields a *stream* of `result`s — the
   request/notification/response triad does not map cleanly.
2. JSON-RPC has no per-stream ordering, deduplication, cursor, or resume
   semantics; AIP would re-layer them as an overlay anyway.
3. AIP's cross-cutting fields (`session`, `seq`, `source`) belong on
   every message; JSON-RPC would bury them in `params`.
4. The semantic core is binding-agnostic: a JSON-RPC **binding** can be
   offered later as a profile without changing the protocol.

#### C.4 Zero Kernel actions

The 13-action sketch of earlier drafts mixed abstraction layers
(`click` is UI, `execute` is dangerously broad, `approve` is business
semantics). Kernel-defined actions would become protocol-level tech
debt. Registries are executor-defined; the Kernel defines only the
invocation mechanism.

#### C.5 Risk is deployment policy, not protocol

"Read patient data" may be riskier than "click submit". Risk taxonomies
vary by organization. The Kernel only states *actions carry opaque
policy metadata*; taxonomies live in profiles.

#### C.6 One binding in v0.1

Transport semantics (ordering, resume, timeout, heartbeat) are a large
surface. MCP's own evolution shows transports need extensive
specification; standardizing a second binding is a ratified amendment,
not a v0.1 feature.

#### C.7 Retryability is declared, never guessed

Receivers report `retry: {allowed, after_ms}` with errors; the decision
engine must not infer retryability from an error code alone. Static
code→retryable tables over-generalize (e.g. `target_not_found` may be
permanent for a deleted button but transient for a slow render — those
are executor-domain facts, not protocol facts).

#### C.8 `ts` is informational

Wall clocks drift; ordering uses `seq`; timeouts use monotonic clocks.
This is stated normatively (I8) because every distributed protocol gets
this wrong at least once.

#### C.9 Context via action, not message

`context.get` as an action reuses the full reliability machinery
(ACK, retry, dedup, resume) for free, and keeps the message-type budget
at four.

#### C.10 Async core, sync façades

The Kernel is asynchronous by design: events are unsolicited
observations, one `action` produces a *stream* of `result`s
(accepted/running → terminal), and the E→D→A→R loop is event-driven.
AIP's target domain — RPA and AI-driven automation — is dominated by
waiting on the external world (page loads, element appearance,
long-running ERP transactions, human approval), which is asynchronous by
nature. Adding synchronous request/response semantics to the core would
double every state machine, ordering rule, dedup path, and error
handling path — precisely the "make it fat" failure the complexity
budget exists to prevent.

"Synchronous" is a **correlation special case, not a transport mode**:
`in_reply_to` + waiting for the terminal result is a complete
synchronous experience over an asynchronous core. Nothing new is needed
in the protocol. Where blocking semantics are genuinely useful, they
belong in the surface layers, never in the core:

- **SDK helpers**: `wait_terminal(action_id, timeout)` — async
  transport, synchronous-looking API
- **Gateway façade**: a request/response binding (e.g. HTTP
  POST /actions that returns after the terminal result) — a future
  profile (SPEC §9.7), never a core message mode
- **Executor adapters**: wrap existing synchronous APIs (ERP REST, etc.)
  as async actions — await inside the executor, protocol unchanged

### D. Repository layout (target)

```
aip/
├── SPEC.md              ← this document
├── README.md
├── INTEGRATION.md       ← executor & agent integration reference
├── spec/                ← ratified amendments & profiles
├── schema/              ← aip.json (JSON Schema for envelope + 4 messages)
├── sdk/
│   ├── python/
│   └── typescript/
├── examples/
│   └── hello-rpa/
├── conformance/
│   └── tests/           ← the suite in §10
├── benchmarks/          ← cost experiment (Appendix E)
└── LICENSE
```

### E. Benchmark protocol

The core hypothesis — *short messages + externalized state + on-demand
context materially lower automation cost* — MUST be validated by
experiment, not intuition. **The metric is context reduction at
equivalent task success rate**; there is no preset byte target, because
a correct 5 KB decision beats a wrong 200-byte one.

**Benchmark task:** auto-login to ERP → query order → modify status →
submit → fetch result.

**Implementations:**

```
A. Traditional long-context agent
B. MCP agent
C. AIP + Context-on-Demand profile
D. C + small model
E. C + rule + small model + LLM cascade
```

**Metrics:**

```
context size per decision (input tokens)
total input/output tokens per task
LLM calls per task
latency
failure rate / recovery rate
action count
COST PER SUCCESSFUL TASK        ← headline metric
```

**Pass condition:** AIP implementations must demonstrate a
context/cost reduction at a task success rate statistically equivalent
to the baseline — not a raw token figure. If tokens drop 95% while
errors triple, the protocol failed.

**Reference implementation:** `benchmarks/` (simulation mode: scripted
decisions, equalized success; real-API mode is a documented TODO).

---

*Kernel v0.1 · 4 message types · 9 envelope fields (7 required) ·
0 kernel actions · 1 binding (WebSocket) · per-(session, source)
sequences · 6 action states · 10 error codes · 10 invariants · 1
complexity budget.*
