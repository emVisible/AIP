# hello-rpa

The minimal end-to-end AIP reference: a **rule-based agent** (zero LLM),
a **reference gateway**, and a **scripted executor** completing one real
business task — *submit an order* — over the E→D→A→R loop.

## Run

```bash
python3 examples/hello-rpa/run.py
```

Uses the Python SDK over an in-memory transport. No external deps.

## Flow

```
executor --event button.appeared-----> gateway --event--> agent (decide)
agent    --action browser.click------> gateway --action--> executor
executor --result accepted/running/ok-> gateway --result--> agent
executor --event order.requires_review (context: ctx_order_1, ref only)
agent    --action context.get (fields on demand) ---------> executor
executor --result ok (only requested fields) -------------> agent
agent    --action erp.order.approve-> gateway --action--> executor
executor --result ok----------------> gateway --result--> agent
executor --event order.submitted----> gateway --event--> agent (done)
```

The order data never leaves the executor's context store (`executor.py`,
`ContextStore`): the decision engine sees only a `context` reference and
fetches the fields it needs via the `context.get` action (SPEC §9.2).
No chat, no long context, no bulk payloads.

The gateway is the only place policy lives (SPEC §8); the agent holds no
execution state; the executor knows nothing about decisions.

## Files

| File | Role |
|------|------|
| `gateway.py` | Reference gateway: routing, ordering, dedup/idempotency, lifecycle, policy, credential scan, timeout/retry, resume (also drives the behavior conformance suite) |
| `agent.py` | Rule-based decision engine (decide by event name; fetches context on demand) |
| `executor.py` | Scripted RPA: acknowledges actions, emits semantic events, owns the ContextStore |
| `run.py` | Wires the three over an in-memory transport and prints the loop |

Try it with a policy that blocks approval — the gateway replies
`result: rejected`, the agent stops, and nothing reaches the executor:

```bash
python3 -c "
import sys; sys.path[:0] = ['examples/hello-rpa', 'sdk/python']
from aip import make_action
from gateway import Gateway
g = Gateway('s_demo', policy={'require_approval': ['erp.order.approve']},
            identities={'executor':'rpa_001','agent':'agent_001'})
out = g.receive('agent', make_action('s_demo','agent_001','erp.order.approve',target='order_1',seq=1).to_dict())
print('gateway executions:', g.executions)
print('reply:', out[0].payload)
"
```