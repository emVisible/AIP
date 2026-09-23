"""Laya sidecar：把 torch 系重依赖隔离在独立进程，Clearance 主产品经 HTTP 调用。

    cd laya_sidecar && uv sync              # 建独立 venv（需联网，约 2GB）
    uv run --no-sync python server.py        # :8685

端点：
    GET  /health
    POST /decide  {kind?, text?, state?, questions?}
                  → {ok, answers, routing, latency_ms, device, engine}

环境变量：
    SIDECAR_PORT   监听端口（默认 8685）
    MODEL_DIR      覆盖 checkpoint（本地微调产物目录或 Hub repo，默认官方包）
    LAYA_LAZY=1    跳过启动预热，首次 /decide 时加载（默认启动即 preload）
    LAYA_MAX_LOADED 常驻 checkpoint 数（默认 2：english + multilingual）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SHORTLIST_K = 20

_router = None
_device = "unknown"
_loaded: list = []


def _router_singleton(preload: bool):
    global _router, _device, _loaded
    if _router is not None:
        return _router
    from laya import Router
    max_loaded = int(os.environ.get("LAYA_MAX_LOADED", "2"))
    _router = Router(max_loaded=max_loaded)
    if preload:
        _router.preload(["english", "multilingual"])
        _loaded = list(_router.loaded)
        try:
            _device = str(_router.load("english").device)
        except Exception:
            pass
    return _router


def _maybe_shortlist(router, state, questions: dict) -> dict:
    """任一 choice 选项超 20 时自动 shortlist（laya 高基数约束），否则原样。"""
    try:
        from laya import embed_fn_from_agent  # type: ignore
        from laya.shortlist import shortlist_choice  # type: ignore
    except Exception:
        return questions
    out = dict(questions)
    agent = router.load(router.route(state, questions)["model"])
    for qid, q in questions.items():
        crit = (q.get("criteria") or {})
        if q.get("type") == "choice" and len(crit) > SHORTLIST_K:
            keep = shortlist_choice(state, crit, embed_fn_from_agent(agent),
                                    k=SHORTLIST_K)
            nq = dict(q)
            nq["criteria"] = {k: crit[k] for k in keep if k in crit}
            out[qid] = nq
    return out


def decide_once(state, questions: dict) -> dict:
    t0 = time.time()
    router = _router_singleton(preload=False)
    questions = _maybe_shortlist(router, state, questions)
    res = router.predict(state, questions)
    global _loaded
    _loaded = list(router.loaded)
    return {"ok": True, "answers": res.get("answers", {}),
            "routing": res.get("routing", {}),
            "latency_ms": int((time.time() - t0) * 1000),
            "device": _device, "engine": "laya"}


def _send(h: BaseHTTPRequestHandler, code: int, obj: dict) -> None:
    body = json.dumps(obj, ensure_ascii=False).encode()
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "LayaSidecar/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("sidecar: " + fmt % args + "\n")

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            _send(self, 200, {"ok": True, "engine": "laya",
                              "device": _device, "loaded": _loaded,
                              "model_dir": os.environ.get("MODEL_DIR", "hub-default")})
        else:
            _send(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/decide":
            _send(self, 404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode() or "{}")
        except ValueError:
            _send(self, 400, {"ok": False, "error": "invalid JSON"})
            return
        state = payload.get("state") or {"kind": payload.get("kind", "other"),
                                         "text": payload.get("text", "")}
        questions = payload.get("questions")
        if not questions:
            _send(self, 400, {"ok": False, "error": "questions required"})
            return
        try:
            _send(self, 200, decide_once(state, questions))
        except Exception as e:
            _send(self, 500, {"ok": False, "error": f"{type(e).__name__}: {e}"})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("SIDECAR_PORT", "8685")))
    p.add_argument("--preload", action="store_true", default=True)
    p.add_argument("--lazy", action="store_true", default=False)
    a = p.parse_args()
    lazy = a.lazy or os.environ.get("LAYA_LAZY", "") == "1"
    try:
        _router_singleton(preload=not lazy)
        print(f"sidecar: router ready (loaded={_loaded} device={_device})", flush=True)
    except Exception as e:
        print(f"sidecar: preload failed ({e}); lazy mode, first /decide will load",
              flush=True)
    print(f"Laya sidecar on http://127.0.0.1:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
