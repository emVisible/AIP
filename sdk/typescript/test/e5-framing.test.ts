/**
 * E5 framing test (SPEC §10 E5): a WebSocket text frame carries exactly one
 * JSON document. Covers parseFrame (unit) and a real ws round trip.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseFrame, WsServerTransport, WsClientTransport } from "../src/transport.js";
import { makeEvent, makeResult } from "../src/messages.js";

const valid = {
  v: 1,
  type: "event",
  id: "evt_e5",
  session: "s_e5",
  seq: 1,
  ts: 0,
  source: "rpa_001",
  payload: { name: "button.appeared", data: { id: "confirm" } },
};

test("parseFrame accepts exactly one JSON object per frame", () => {
  const ok = parseFrame(JSON.stringify(valid));
  assert.equal(ok.error, undefined);
  assert.equal(ok.message?.id, "evt_e5");
});

test("parseFrame rejects two JSON objects in one frame (E5)", () => {
  const two = `${JSON.stringify(valid)}${JSON.stringify(valid)}`;
  const r = parseFrame(two);
  assert.ok(r.error, "expected invalid frame");
});

test("parseFrame rejects trailing garbage and non-object JSON", () => {
  assert.ok(parseFrame(`${JSON.stringify(valid)} garbage`).error);
  assert.ok(parseFrame("").error);
  assert.ok(parseFrame("[1,2,3]").error);
  assert.ok(parseFrame('"just a string"').error);
});

test("ws server <-> client round trip carries one message per frame", async () => {
  const server = new WsServerTransport({ onError: () => {} });
  await new Promise((resolve) => server.server.once("listening", resolve));
  const url = `ws://127.0.0.1:${server.port()}`;

  const received: unknown[] = [];
  const client = new WsClientTransport(url, {
    onMessage: (m) => received.push(m),
    onError: (e) => {
      throw e;
    },
  });

  // wait for connection
  await new Promise((resolve) => {
    const check = () => (server["socket"] ? resolve(null) : setTimeout(check, 5));
    check();
  });

  server.send(makeEvent("s_e5", "rpa_001", "button.appeared", { id: "confirm" }));
  server.send(makeResult("s_e5", "rpa_001", "ok", "act_1"));
  await new Promise((r) => setTimeout(r, 50));

  assert.equal(received.length, 2);
  assert.equal((received[0] as any).payload.name, "button.appeared");
  assert.equal((received[1] as any).payload.status, "ok");

  client.close();
  await server.close();
});