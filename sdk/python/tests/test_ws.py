#!/usr/bin/env python3
"""WebSocket binding tests (SPEC §7.1, §10 E5). Requires: pip install aip[ws].
Run: python3 sdk/python/tests/test_ws.py"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aip import make_event  # noqa: E402
from aip.ws import WsClient, WsServer, parse_frame  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def test_parse_frame():
    msg = {"v": 1, "type": "event", "id": "e", "session": "s", "seq": 1, "ts": 0,
           "source": "rpa", "payload": {"name": "x"}}
    m, err = parse_frame(json.dumps(msg))
    check("single JSON object -> message", err is None and m.id == "e")
    _, err = parse_frame(json.dumps(msg) + json.dumps(msg))
    check("two objects in one frame -> error (E5)", err is not None)
    _, err = parse_frame("not json")
    check("garbage -> error", err is not None)
    _, err = parse_frame("[1,2]")
    check("non-object JSON -> error", err is not None)
    _, err = parse_frame("")
    check("empty frame -> error", err is not None)


async def test_round_trip():
    received = []
    errors = []
    server = WsServer(on_message=lambda m: received.append(m), on_error=lambda e, f: errors.append(e))
    port = await server.start()
    client = await WsClient(f"ws://127.0.0.1:{port}", on_message=lambda m: received.append(m)).connect()
    task = asyncio.create_task(client.run())
    await server.send(make_event("s_ws", "rpa_001", "button.appeared", {"id": "confirm"}))
    await asyncio.sleep(0.1)
    check("ws round trip delivers message", len(received) == 1 and received[0].payload["name"] == "button.appeared")
    await client.send_text('{"a":1}{"b":2}')
    await asyncio.sleep(0.1)
    check("bad frame triggers on_error (E5)", len(errors) == 1)
    await client.close()
    task.cancel()
    await server.close()


def main():
    print("WebSocket binding tests (SPEC §7.1, E5)")
    test_parse_frame()
    asyncio.run(test_round_trip())
    print(f"\n{FAIL} failed, {PASS} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())