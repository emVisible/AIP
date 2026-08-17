# AIP — Python SDK (Kernel v0.1)

Minimal implementation of the AIP Kernel (see `SPEC.md`): the four
message types, per-stream sequencing, action lifecycle & idempotency,
sessions with cursors, Context-on-Demand, and transports (in-memory +
WebSocket binding).

```python
from aip import AIPPeer

peer = AIPPeer(source="rpa_001", session_id="s_001", transport=endpoint)

peer.send_event("button.appeared", data={"id": "confirm"})
peer.send_result("ok", in_reply_to="act_123")
```

## Profiles implemented

- **Context-on-Demand** (`aip/context.py`, SPEC §9.2): addressable,
  versioned, expiring context objects; `context.get` is an ordinary
  action answered by a normal result.

```python
from aip import ContextStore

store = ContextStore()
store.put("ctx_order_1", {"total": 299.0, "customer": "c_001"})
data, err = store.get("ctx_order_1", fields=["total"])  # -> ({'total': 299.0}, None)
```

- **Action Registry** (`aip/registry.py`, SPEC §9.3): idempotency,
  timeout, and retry counts are Registry properties — never per-call
  parameters on the action message.

## Transports

- `aip.transport.Endpoint` / `Wire` — in-memory (tests, local demos).
- `aip.ws.WsServer` / `WsClient` — WebSocket binding (the only Kernel
  binding, SPEC §7.1), requiring `pip install aip[ws]` (websockets).
  Implements E5: one JSON document per frame.

```python
import asyncio
from aip.ws import WsServer, WsClient
from aip import make_event

async def main():
    server = WsServer(on_message=lambda m: print("server got", m.id))
    port = await server.start()
    client = await WsClient(f"ws://127.0.0.1:{port}").connect()
    await client.send(make_event("s_1", "rpa_001", "button.appeared"))
    await asyncio.sleep(0.1)
    await client.close()
    await server.close()

asyncio.run(main())
```

## Tests

```bash
python3 sdk/python/tests/test_context.py   # ContextStore (SPEC §9.2)
python3 sdk/python/tests/test_ws.py        # WebSocket binding + E5 framing
```

Schema validation is optional (`pip install aip[validate]`); the
authoritative validator is `schema/aip.json` (used by the conformance
suite and the TypeScript SDK).

This SDK implements the Kernel plus reference profiles. Policy lives in
the gateway (see `examples/hello-rpa/gateway.py`).