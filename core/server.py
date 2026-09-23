"""Clearance HTTP API（stdlib only，无第三方依赖）。

    python3 -m core.server [--port 8686] [--data ./data]

端点：
    GET  /api/health                      # 引擎 + sidecar 明细（device/loaded）
    GET  /api/queue?state=pending|approved|rejected
    POST /api/review/submit   {kind,title,body,meta?}
    POST /api/review/<id>/resolve  {outcome: approve|reject, actor?}
    POST /api/context/get     {ref, fields} — CoD 真读写，禁 ["*"]
    GET  /api/stats
    GET  /api/events                      # SSE：hello 快照 + submitted/resolved/stats
"""
from __future__ import annotations

import argparse
import json
import os
import queue as queue_mod
import sys
import threading
import urllib.request
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.decide import engine_name  # noqa: E402
from core.engines import _sidecar_url  # noqa: E402
from core.store import ReviewStore  # noqa: E402

VERSION = "0.1.0"


class EventHub:
    """内存 SSE 订阅中心：submit/resolve 后广播，断线自动清理。"""

    def __init__(self):
        self._subs: list = []
        self._lock = threading.Lock()

    def subscribe(self):
        q: queue_mod.Queue = queue_mod.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, etype: str, data: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait({"type": etype, "data": data})
            except queue_mod.Full:
                pass


def _send(handler: BaseHTTPRequestHandler, code: int, obj: dict) -> None:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body)


def _sidecar_health() -> dict | None:
    try:
        with urllib.request.urlopen(_sidecar_url() + "/health", timeout=0.5) as r:
            return json.load(r)
    except Exception:
        return None


def _counts(store: ReviewStore) -> dict:
    import datetime as _dt
    today = _dt.date.today().isoformat()
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    today_counts = {"pending": 0, "approved": 0, "rejected": 0}
    items = store.queue("")
    for r in items:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        ts = (r.get("item") or {}).get("ts", 0)
        try:
            day = _dt.datetime.fromtimestamp(ts / 1000).date().isoformat()
        except (ValueError, TypeError, OSError):
            day = ""
        if day == today and r["state"] in today_counts:
            today_counts[r["state"]] += 1
    return {"counts": counts, "total": len(items), "today": today_counts}


def make_handler(store: ReviewStore, hub: EventHub):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Clearance/0.2"

        def log_message(self, fmt, *args):  # 安静日志
            sys.stderr.write("clearance: " + fmt % args + "\n")

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ValueError("invalid JSON body")

        def do_OPTIONS(self):
            _send(self, 204, {})

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                _send(self, 200, {"ok": True, "engine": engine_name(),
                                  "version": VERSION,
                                  "sidecar": _sidecar_health()})
            elif parsed.path == "/api/queue":
                state = parse_qs(parsed.query).get("state", [""])[0]
                if state not in ("", "pending", "approved", "rejected"):
                    _send(self, 400, {"ok": False, "error": "bad state"})
                    return
                _send(self, 200, {"ok": True, "items": store.queue(state)})
            elif parsed.path == "/api/stats":
                _send(self, 200, {"ok": True, **_counts(store),
                                  "engine": engine_name()})
            elif parsed.path == "/api/events":
                self._serve_sse()
            else:
                _send(self, 404, {"ok": False, "error": "not found"})

        def _serve_sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            q = hub.subscribe()
            try:
                hello = {"engine": engine_name(), **_counts(store)}
                self.wfile.write(
                    f"event: hello\ndata: {json.dumps(hello)}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        ev = q.get(timeout=15)
                        self.wfile.write(
                            f"event: {ev['type']}\ndata: "
                            f"{json.dumps(ev['data'], ensure_ascii=False)}\n\n"
                            .encode())
                    except queue_mod.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
            except ValueError as e:
                _send(self, 400, {"ok": False, "error": str(e)})
                return
            if parsed.path == "/api/context/get":
                try:
                    out = store.context_get(str(payload.get("ref", "")),
                                            payload.get("fields", []))
                except ValueError as e:
                    _send(self, 400, {"ok": False, "error": str(e)})
                    return
                except OSError:
                    _send(self, 404, {"ok": False, "error": "context not found"})
                    return
                _send(self, 200, {"ok": True, **out})
            elif parsed.path == "/api/review/submit":
                rec = store.submit(str(payload.get("kind", "other")),
                                   str(payload.get("title", "")),
                                   str(payload.get("body", "")),
                                   payload.get("meta") or {},
                                   on_progress=lambda t, d: hub.publish(t, d))
                hub.publish("submitted", {"id": rec.item.id, "state": rec.state,
                                          **_counts(store)})
                hub.publish("stats", _counts(store))
                _send(self, 200, {"ok": True, **asdict(rec)})
            elif parsed.path.startswith("/api/review/") and parsed.path.endswith("/resolve"):
                rid = parsed.path[len("/api/review/"):-len("/resolve")]
                try:
                    rec = store.resolve(rid, payload.get("outcome", ""),
                                        str(payload.get("actor", "admin")))
                except KeyError:
                    _send(self, 404, {"ok": False, "error": "review not found"})
                    return
                except ValueError as e:
                    _send(self, 400, {"ok": False, "error": str(e)})
                    return
                hub.publish("resolved", {"id": rid, "state": rec["state"],
                                         **_counts(store)})
                hub.publish("stats", _counts(store))
                _send(self, 200, {"ok": True, **rec})
            else:
                _send(self, 404, {"ok": False, "error": "not found"})

    return Handler


def serve(port: int = 8686, data_dir: str = "") -> ThreadingHTTPServer:
    data_dir = data_dir or os.environ.get("CLEARANCE_DATA_DIR", "") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    store = ReviewStore(data_dir)
    hub = EventHub()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, hub))
    except OSError as e:
        print(f"Clearance API: 端口 {port} 被占用（{e}）。"
              f"先停掉旧进程：lsof -ti:{port} | xargs kill，或换 PORT 再起。",
              flush=True)
        raise SystemExit(1)
    print(f"Clearance API on http://127.0.0.1:{port} (data={data_dir} engine={engine_name()})",
          flush=True)
    return server


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("PORT", "8686")))
    p.add_argument("--data", default="")
    a = p.parse_args()
    serve(a.port, a.data).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
