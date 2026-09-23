"""Laya sidecar：把 torch 系重依赖隔离在独立进程，Clearance 主产品经 HTTP 调用。

    cd laya_sidecar && uv sync              # 建独立 venv（需联网，约 2GB）
    uv run --no-sync python server.py        # :8685

端点：
    GET  /health
    POST /decide  {kind?, text?, state?, questions, lang_guess?}
                  → {ok, answers, routing, shortlisted, latency_ms, device, engine}

环境变量：
    SIDECAR_PORT    监听端口（默认 8685）
    MODEL_DIR       覆盖 checkpoint（本地微调产物目录或 Hub repo，默认官方包）
    LAYA_DEFAULT    路由默认 checkpoint（默认 multilingual：中文优先）
    LAYA_LAZY=1     跳过启动预热，首次 /decide 时加载（默认启动即 preload）
    LAYA_MAX_LOADED 常驻 checkpoint 数（默认 2：english + multilingual）
    LAYA_HEAD_MAX_LEN 覆盖选项 token 预算（默认不覆盖；高基数时官方建议调大
                      或走 shortlist，本服务超 20 项自动 shortlist）
    SHORTLIST_K     shortlist 保留数（默认 20）

实现对照（laya 官方 API，vendored 于 reference/laya）：
    Router(default, lang_guess) / router.predict(..., lang_guess)
    laya.predict_shortlist(router, state, questions, embed_fn, k)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from clearance_core.calibration import load_table, rescale_answers
    _HAS_CAL = True
except Exception as _cal_err:  # 主产品缺席时 sidecar 照常跑，只是无校准
    print(f"sidecar: calibration math unavailable ({_cal_err}); serving raw", flush=True)
    _HAS_CAL = False

_router = None
_device = "unknown"
_loaded: list = []
_default = os.environ.get("LAYA_DEFAULT", "multilingual")
_shortlist_k = int(os.environ.get("SHORTLIST_K", "20"))


def _router_singleton(preload: bool):
    global _router, _device, _loaded
    if _router is not None:
        return _router
    from laya import Router
    _router = Router(default=_default,
                     max_loaded=int(os.environ.get("LAYA_MAX_LOADED", "2")))
    if preload:
        want = [m.strip() for m in
                os.environ.get("LAYA_PRELOAD", "english,multilingual").split(",")
                if m.strip()]
        _router.preload(want)
        _loaded = list(_router.loaded)
        try:
            _device = str(_router.load("english").device)
        except Exception:
            pass
    return _router


def _apply_head_budget(router, model: str) -> None:
    override = os.environ.get("LAYA_HEAD_MAX_LEN", "")
    if not override:
        return
    try:
        agent = router.load(model)
        agent.cfg["head_max_len"] = int(override)
    except Exception as e:
        print(f"sidecar: head_max_len override failed: {e}", flush=True)


def _needs_shortlist(questions: dict) -> bool:
    return any(isinstance(q, dict) and q.get("type") == "choice"
               and len(q.get("criteria") or {}) > _shortlist_k
               for q in questions.values())


_cal_table: dict = {}
_cal_mtime = -1.0


def _calibration_table() -> dict:
    """拟合温度表（mtime 热重载；缺席/损坏即 {}，出厂行为）。"""
    global _cal_table, _cal_mtime
    if not _HAS_CAL:
        return {}
    path = os.environ.get("CALIBRATION_FILE", "") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "eval", "calibration.json")
    try:
        m = os.path.getmtime(path)
    except OSError:
        return {}
    if m != _cal_mtime:
        _cal_table = load_table(path)
        _cal_mtime = m
        if _cal_table:
            print(f"sidecar: calibration loaded ({len(_cal_table)} questions)", flush=True)
    return _cal_table


def decide_once(state, questions: dict, lang_guess=None) -> dict:
    t0 = time.time()
    router = _router_singleton(preload=False)
    import inspect as _inspect
    route_kw: dict = {}
    if lang_guess and "lang_guess" in _inspect.signature(router.route).parameters:
        route_kw["lang_guess"] = lang_guess
    routed = router.route(state, questions, **route_kw)
    model = routed["model"]
    _apply_head_budget(router, model)
    shortlisted = False
    predict_kw: dict = {}
    if "lang_guess" in _inspect.signature(router.predict).parameters:
        predict_kw["lang_guess"] = lang_guess
    if _needs_shortlist(questions):
        from laya import embed_fn_from_agent, predict_shortlist
        agent = router.load(model)
        res = predict_shortlist(router, state, questions,
                                embed_fn_from_agent(agent),
                                k=_shortlist_k, model=model,
                                **predict_kw)
        shortlisted = True
    else:
        res = router.predict(state, questions, **predict_kw)
    global _loaded
    _loaded = list(router.loaded)
    answers, calibrated = rescale_answers(res.get("answers", {}), _calibration_table()) \
        if _HAS_CAL else (res.get("answers", {}), False)
    return {"ok": True, "answers": answers,
            "routing": res.get("routing", {}),
            "shortlisted": shortlisted,
            "calibrated": calibrated,
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
    server_version = "LayaSidecar/0.2"

    def log_message(self, fmt, *args):
        sys.stderr.write("sidecar: " + fmt % args + "\n")

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            _send(self, 200, {"ok": True, "engine": "laya",
                              "device": _device, "loaded": _loaded,
                              "default": _default,
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
            _send(self, 200, decide_once(state, questions,
                                         lang_guess=payload.get("lang_guess")))
        except Exception as e:
            _send(self, 500, {"ok": False, "error": f"{type(e).__name__}: {e}"})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("SIDECAR_PORT", "8685")))
    p.add_argument("--lazy", action="store_true", default=False)
    a = p.parse_args()
    lazy = a.lazy or os.environ.get("LAYA_LAZY", "") == "1"
    try:
        _router_singleton(preload=not lazy)
        print(f"sidecar: router ready (loaded={_loaded} device={_device} default={_default})",
              flush=True)
    except Exception as e:
        print(f"sidecar: preload failed ({e}); lazy mode, first /decide will load",
              flush=True)
    print(f"Laya sidecar on http://127.0.0.1:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
