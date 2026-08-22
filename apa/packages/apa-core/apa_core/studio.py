"""apa-core: APA-Studio v1 — 最小管理界面（设计文档 §16.1「仅 Session 日志查看」）。

零依赖（stdlib http.server）。功能：
    GET /                      会话总览页（自动刷新）
    GET /api/sessions          所有已加载 journal 的会话摘要 JSON
    GET /api/sessions/<id>     单会话状态/游标/任务/统计
    GET /api/audit             审计日志尾部
    POST /api/tasks/<id>/resolve   人工任务解析（需 --control 开启）

用法：
    python -m apa_core.studio --journals data/*.jsonl --port 8686
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .persist import journal_records

_HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>APA Studio</title>
<meta http-equiv="refresh" content="3">
<style>
 body{font-family:-apple-system,sans-serif;margin:24px;background:#fafafa;color:#222}
 h1{font-size:20px} h2{font-size:15px;margin-top:20px}
 table{border-collapse:collapse;width:100%;background:#fff}
 th,td{border:1px solid #ddd;padding:6px 10px;text-align:left;font-size:13px}
 th{background:#f0f0f0} code{font-size:12px}
 .RUNNING{color:#1565c0}.COMPLETED{color:#2e7d32}
 .FAILED,.CANCELLED{color:#c62828}.SUSPENDED{color:#e65100}
</style></head><body>
<h1>APA Studio <span style="font-size:12px;color:#888">— sessions &amp; audit</span></h1>
__BODY__
</body></html>

<!--
  人工任务交互（HITL）：按钮经 fetch 调用 /api/tasks/<id>/resolve，
  由 StudioServer.resolve_task 回调注入完成事件并恢复挂起的会话。
-->"""


def collect_sessions(journal_paths: List[str]) -> Dict[str, dict]:
    sessions: Dict[str, dict] = {}
    for path in journal_paths:
        for rec in journal_records(path):
            sid = rec.get("session", "")
            if not sid:
                continue
            s = sessions.setdefault(sid, {
                "journal": path, "state": "INITIALIZING", "cursors": {},
                "tasks_open": [], "outcome": None, "last_ts": 0,
                "tenant": rec.get("tenant"),
            })
            kind = rec.get("kind")
            if kind == "state":
                s["state"] = rec.get("to", s["state"])
                s["last_ts"] = max(s["last_ts"], rec.get("ts", 0))
            elif kind == "cursor":
                s["cursors"][rec.get("source", "?")] = rec.get("seq", 0)
                s["last_ts"] = max(s["last_ts"], rec.get("ts", 0))
            elif kind == "task":
                tid = rec.get("task_id")
                if rec.get("status") == "resolved":
                    s["tasks_open"] = [t for t in s["tasks_open"]
                                       if t.get("task_id") != tid]
                else:
                    s["tasks_open"].append({"task_id": tid,
                                            "task_type": rec.get("task_type", "")})
            elif kind == "outcome":
                s["outcome"] = rec.get("outcome")
    return sessions


def render_html(sessions: Dict[str, dict], audit_tail: List[dict]) -> str:
    rows = []
    for sid, s in sorted(sessions.items()):
        state_cls = s["state"]
        cursors = ", ".join(f"{k}:{v}" for k, v in s["cursors"].items()) or "—"
        task_names = ", ".join(t.get("task_id", "?")
                               for t in s["tasks_open"]) or "—"
        rows.append(
            f"<tr><td><code>{sid}</code></td>"
            f"<td class='{state_cls}'>{s['state']}</td>"
            f"<td>{s['outcome'] or '—'}</td>"
            f"<td>{cursors}</td><td>{task_names}</td>"
            f"<td><code>{s['journal']}</code></td></tr>")
    table = ("<h2>Sessions</h2><table><tr><th>Session</th><th>State</th>"
             "<th>Outcome</th><th>Cursors</th><th>Open Tasks</th>"
             "<th>Journal</th></tr>" + "".join(rows) + "</table>") if rows \
        else "<p>（无会话日志；用 --journals 指定 journal 文件）</p>"
    task_rows = []
    for sid, sess in sorted(sessions.items()):
        for t in sess.get("tasks_open", []):
            tid = t.get("task_id", "")
            ttype = t.get("task_type", "")
            task_rows.append(
                f"<tr><td><code>{tid}</code></td><td>{ttype}</td>"
                f"<td>{sid}</td>"
                f"<td>"
                f"<button onclick=\"resolveTask('{tid}','approve')\">批准</button>"
                f"<button onclick=\"resolveTask('{tid}','reject')\">驳回</button>"
                f"<button onclick=\"resolveTask('{tid}','retry')\">重试</button>"
                f"</td></tr>")
    tasks_html = (
        "<h2>Human Tasks（人工审批）</h2>"
        "<table><tr><th>Task</th><th>Type</th><th>Session</th>"
        "<th>Action</th></tr>" + "".join(task_rows) + "</table>"
        "<script>function resolveTask(id, outcome){"
        "fetch('/api/tasks/' + id + '/resolve', {method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body: JSON.stringify({outcome: outcome})})"
        ".then(function(){location.reload()});}</script>"
    ) if task_rows else ""
    audit_rows = "".join(
        f"<tr><td><code>{a.get('kind', a.get('audit_id', ''))}</code></td>"
        f"<td>{json.dumps(a, ensure_ascii=False)[:160]}</td></tr>"
        for a in audit_tail)
    audit = ("<h2>Audit tail</h2><table><tr><th>Kind</th><th>Record</th></tr>"
             + audit_rows + "</table>") if audit_tail else ""
    return _HTML.replace("__BODY__", tasks_html + table + audit)


class StudioHandler(BaseHTTPRequestHandler):
    studio: "StudioServer"

    def log_message(self, *a):  # 静默
        pass

    def _authorized(self) -> bool:
        want = self.studio.token
        if not want:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {want}"

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._authorized():
            self._send(b'{"error":"unauthorized"}', "application/json", 401)
            return
        st = self.studio
        if self.path == "/api/sessions":
            self._send(json.dumps(st.sessions(), ensure_ascii=False).encode(),
                       "application/json")
        elif self.path.startswith("/api/sessions/"):
            sid = self.path.rsplit("/", 1)[-1]
            data = st.sessions().get(sid)
            self._send(json.dumps(data or {"error": "not_found"},
                                  ensure_ascii=False).encode(),
                       "application/json")
        elif self.path == "/api/audit":
            self._send(json.dumps(st.audit_tail(), ensure_ascii=False).encode(),
                       "application/json")
        elif self.path.startswith("/api/journal/stream"):
            self._stream_journal()
        elif self.path == "/api/analytics":
            from .analytics import summarize
            data = summarize(st.journal_paths, tenant=st.tenant)
            self._send(json.dumps(data, ensure_ascii=False).encode(),
                       "application/json")
        elif self.path == "/api/registry/actions":
            self._send(json.dumps(st.registry_actions(),
                                  ensure_ascii=False).encode(),
                       "application/json")
        elif self.path == "/design":
            self._send(DESIGN_HTML.replace("__BODY__", "").encode()
                       if False else render_design_page(st).encode(),
                       "text/html; charset=utf-8")
        elif self.path == "/api/processes":
            self._send(json.dumps(st.list_processes(),
                                  ensure_ascii=False).encode(),
                       "application/json")
        elif self.path == "/api/processes/to-form":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            try:
                form = st.process_to_form(str(body.get("yaml", "")))
                self._send(json.dumps(form, ensure_ascii=False).encode(),
                           "application/json")
            except Exception as e:  # noqa: BLE001
                self._send(json.dumps({"error": str(e)},
                                      ensure_ascii=False).encode(),
                           "application/json", 400)
        elif self.path == "/api/processes/from-form":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            try:
                yaml_text = st.process_from_form(body.get("form", {}))
                self._send(json.dumps({"yaml": yaml_text},
                                      ensure_ascii=False).encode(),
                           "application/json")
            except Exception as e:  # noqa: BLE001
                self._send(json.dumps({"error": str(e)},
                                      ensure_ascii=False).encode(),
                           "application/json", 400)
        elif self.path == "/design":
            self._send(render_design_page(st).encode(),
                       "text/html; charset=utf-8")
        elif self.path == "/design.js":
            self._send(_DESIGNER_JS.encode(), "application/javascript")
        elif self.path.startswith("/api/processes/get/"):
            pid = self.path.rsplit("/", 1)[-1]
            content = st.load_process_yaml(pid)
            if content is None:
                self._send(json.dumps({"error": "not_found"}).encode(),
                           "application/json", 404)
            else:
                self._send(json.dumps({"id": pid, "yaml": content},
                                      ensure_ascii=False).encode(),
                           "application/json")
        elif self.path == "/api/registry/actions":
            self._send(json.dumps(st.registry_actions(),
                                  ensure_ascii=False).encode(),
                       "application/json")
        else:
            self._send(render_html(st.sessions(), st.audit_tail()).encode(),
                       "text/html; charset=utf-8")

    def do_POST(self):
        if not self._authorized():
            self._send(b'{"error":"unauthorized"}', "application/json", 401)
            return
        # /api/tasks/<task_id>/resolve  → 需要注册的 resolver 回调
        parts = self.path.strip("/").split("/")
        if self.path == "/api/events":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            cb = self.studio.dispatch_event_cb
            if cb is None:
                self._send(json.dumps(
                    {"error": "event dispatch not configured"}).encode(),
                    "application/json", 501)
                return
            result = cb(str(body.get("name", "")),
                        body.get("data") or {})
            self._send(json.dumps(result, ensure_ascii=False).encode(),
                       "application/json")
            return
        if self.path == "/api/processes/save":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            result = self.studio.save_process_yaml(
                str(body.get("id", "")), str(body.get("yaml", "")))
            code = 200 if result.get("ok") else 400
            self._send(json.dumps(result, ensure_ascii=False).encode(),
                       "application/json", code)
            return
        if self.path == "/api/processes/test":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            try:
                result = self.studio.test_run_process(
                    str(body.get("yaml", "")),
                    str(body.get("event", "")),
                    body.get("data") or {})
                self._send(json.dumps(result, ensure_ascii=False).encode(),
                           "application/json")
            except Exception as e:  # noqa: BLE001
                self._send(json.dumps(
                    {"outcome": "error", "error": str(e)},
                    ensure_ascii=False).encode(), "application/json")
            return
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks" \
                and parts[3] == "resolve":
            task_id = parts[2]
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            ok = self.studio.resolve_task(task_id, body)
            self._send(json.dumps({"ok": bool(ok)}).encode(), "application/json")
        else:
            self.send_response(404)
            self.end_headers()


class StudioServer:
    def __init__(self, journals: List[str], *, port: int = 8686,
                 audit_tail_size: int = 30,
                 tenant: Optional[str] = None,
                 token: Optional[str] = None,
                 registry=None,
                 processes_dir: Optional[str] = None,
                 dispatch_event: Optional[Callable[[str, dict], dict]] = None,
                 resolve_task=None) -> None:
        # 外部事件入口（serve 模式接 Scheduler.dispatch_event）
        self.dispatch_event_cb = dispatch_event
        # 惰性展开：journal 文件可能在服务启动后才产生（HITL 交互场景）
        self.journal_patterns = list(journals)
        self.port = port
        self.audit_tail_size = audit_tail_size
        self.tenant = tenant          # 多租户过滤（§12.1）
        # token 配置后所有请求须带 Authorization: Bearer <token>（§12.1）
        self.token = token
        self.registry = registry      # 低代码设计器：动作目录数据源
        # 流程 YAML 真相源目录（§10.2；唯一权威，journal 不存流程）
        self.processes_dir = (Path(processes_dir)
                              if processes_dir else
                              Path(__file__).resolve().parents[3]
                              / "data" / "processes")
        self.processes_dir.mkdir(parents=True, exist_ok=True)
        self._resolve = resolve_task
        self._httpd: Optional[ThreadingHTTPServer] = None

    @property
    def journal_paths(self) -> List[str]:
        """每次访问重新展开 glob（文件生命周期与服务器解耦）。"""
        expanded: List[str] = []
        for pattern in self.journal_patterns:
            expanded.extend(glob.glob(pattern))
        return expanded

    def sessions(self) -> Dict[str, dict]:
        all_sessions = collect_sessions(self.journal_paths)
        if self.tenant:
            return {sid: s for sid, s in all_sessions.items()
                    if s.get("tenant") == self.tenant}
        return all_sessions

    # --- 低代码：流程 YAML 真相源（§10.2；唯一权威） ---------------------------
    def list_processes(self) -> List[dict]:
        out: List[dict] = []
        for f in sorted(self.processes_dir.glob("*.yaml")):
            proc_id = f.stem
            try:
                from .process import load_process
                proc = load_process(str(f))
                out.append({"id": proc_id, "process": proc.process_id,
                            "steps": len(proc.steps),
                            "trigger": proc.trigger_name,
                            "valid": True})
            except Exception as e:  # noqa: BLE001
                out.append({"id": proc_id, "valid": False, "error": str(e)})
        return out

    def load_process_yaml(self, proc_id: str) -> Optional[str]:
        if not re.fullmatch(r"[a-z0-9_\-]+", proc_id or ""):
            return None
        f = self.processes_dir / f"{proc_id}.yaml"
        if not f.is_file():
            return None
        return f.read_text(encoding="utf-8")

    def save_process_yaml(self, proc_id: str, yaml_text: str) -> dict:
        """校验后写入真相源。返回 {ok, errors}。id 即文件名 stem。"""
        if not proc_id or not re.fullmatch(r"[a-z0-9_\-]+", proc_id):
            return {"ok": False, "errors": ["id 只允许小写字母/数字/_/-"]}
        import yaml as _yaml
        from .process import build_process
        try:
            data = _yaml.safe_load(yaml_text)
            proc = build_process(data)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "errors": [str(e)]}
        f = self.processes_dir / f"{proc_id}.yaml"
        f.write_text(yaml_text, encoding="utf-8")
        return {"ok": True, "errors": [],
                "process_id": proc.process_id, "steps": len(proc.steps)}

    def test_run_process(self, yaml_text: str, event_name: str,
                         event_data: dict) -> dict:
        """沙盒试运行：MockERP + API 复合执行器，返回步骤轨迹。

        沙盒覆盖 api./erp. 域；browser./desktop. 域需真实执行器，
        在轨迹中以 action_not_supported 反馈（同样是有效验证信息）。
        """
        from .mock_erp import MockERP
        from .launcher import run_process

        erp = MockERP(seed_orders=[{"id": "PO-SANDBOX-1", "status": "pending"}])
        port = erp.start()

        from apa_executors.api_executor import APIExecutor
        from apa_sdk.composite import CompositeExecutor

        def make_executors():
            router = CompositeExecutor("bot_sandbox", "s_sandbox")
            api_mod = APIExecutor("bot_sandbox", "s_sandbox",
                                  base_url=f"http://127.0.0.1:{port}")
            router.register(("api", "erp"), api_mod)
            return [(("api", "erp"), router)]

        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yaml",
                                         delete=False, encoding="utf-8") as fh:
            fh.write(yaml_text)
            holder = fh.name
        try:
            result = run_process(
                holder, event_name, event_data,
                executors=make_executors(),
                session_prefix="s_sandbox",
                timeout_s=10.0,
            )
            steps = [dict(st) for st in result["steps"]]
            return {"outcome": result["outcome"],
                    "gateway_state": result["gateway_state"],
                    "steps": steps}
        finally:
            erp.stop()
            try:
                os.unlink(holder)
            except OSError:
                pass


    # --- 低代码：表单 ↔ YAML 双向转换（序列化权威在服务端 pyyaml） -------------
    def process_to_form(self, yaml_text: str) -> dict:
        """YAML → 表单数据。条件字段剥离 {{ }} 外壳，存原始表达式。"""
        import yaml as _y
        from .process import build_process
        proc = build_process(_y.safe_load(yaml_text))

        def _strip(cond: Optional[str]) -> str:
            if not cond:
                return ""
            inner = cond.strip()
            if inner.startswith("{{") and inner.endswith("}}"):
                inner = inner[2:-2].strip()
            return inner

        steps = [{
            "id": s.id, "type": s.type or "", "action": s.action or "",
            "target": s.target or "",
            "params_json": json.dumps(s.params or {}, ensure_ascii=False),
            "condition": _strip(s.condition),
            "output_as": s.output_as or "",
            "on_failure_goto": (s.on_failure or {}).get("goto", ""),
        } for s in proc.steps]
        handlers = [{
            "key": k, "action": v.action or "",
            "params_json": json.dumps(v.params or {}, ensure_ascii=False),
        } for k, v in proc.error_handlers.items()]
        return {"id": proc.process_id, "mode": proc.mode,
                "trigger_name": proc.trigger_name or "",
                "max_actions": proc.max_actions,
                "steps": steps, "error_handlers": handlers}

    def process_from_form(self, form: dict) -> str:
        """表单数据 → 校验过的 YAML 文本（build_process 把关，C3 违规即报错）。"""
        import yaml as _yaml
        from .process import FORBIDDEN_KEYS, build_process

        # C3：表单层显式拒绝控制键（静默丢弃会让用户误以为已生效）
        for i, s in enumerate(form.get("steps", [])):
            bad = FORBIDDEN_KEYS & set(s.keys())
            if bad:
                raise ValueError(
                    f"步骤 {s.get('id', i)} 携带 {sorted(bad)} —— "
                    "C3：idempotency/risk 只能在 Action Registry 声明")
        for h in form.get("error_handlers", []):
            if isinstance(h.get("params"), dict):
                continue
            bad2 = FORBIDDEN_KEYS & set(h.keys())
            if bad2:
                raise ValueError(
                    f"错误处理器 {h.get('key', '?')} 携带 {sorted(bad2)}（C3）")

        def _wrap(expr: str) -> str:
            expr = (expr or "").strip()
            return f"{{{{ {expr} }}}}" if expr else ""

        steps = []
        for s in form.get("steps", []):
            st: Dict[str, Any] = {"id": str(s.get("id", "")).strip()}
            if s.get("type") == "ai_decision":
                st["type"] = "ai_decision"
                st["params"] = {"available_actions":
                                s.get("available_actions") or []}
            else:
                st["action"] = str(s.get("action", ""))
                if s.get("params_json"):
                    st["params"] = json.loads(s["params_json"])
            if s.get("target"):
                st["target"] = s["target"]
            cond = _wrap(str(s.get("condition", "")))
            if cond:
                st["condition"] = cond
            if s.get("output_as"):
                st["output_as"] = s["output_as"]
            if s.get("on_failure_goto"):
                st["on_failure"] = {"goto": s["on_failure_goto"]}
            steps.append(st)
        handlers = {}
        for h in form.get("error_handlers", []):
            entry: Dict[str, Any] = {"action": h["action"]}
            if h.get("params_json"):
                entry["params"] = json.loads(h["params_json"])
            handlers[h["key"]] = entry
        form_proc = {
            "process": {
                "id": form.get("id", ""),
                "mode": "process",
                "trigger": {"type": "event",
                            "name": form.get("trigger_name", "")},
                "max_actions": int(form.get("max_actions", 50)),
                "steps": steps,
            }
        }
        if handlers:
            form_proc["process"]["error_handlers"] = handlers
        build_process(form_proc)   # 校验（含 C3 检查），不通过即抛错
        return _yaml.safe_dump(form_proc, allow_unicode=True, sort_keys=False)

    def _stream_journal(self) -> None:
        """SSE：text/event-stream 增量推送 journal 记录（按 ts 水位）。"""
        import time as _t
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last_ts = 0.0
        try:
            while True:
                for path in self.journal_paths:
                    for rec in journal_records(path):
                        ts = float(rec.get("ts", 0))
                        if ts > last_ts:
                            last_ts = ts
                            payload = json.dumps(rec, ensure_ascii=False)
                            self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                _t.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            pass  # 客户端断开 → 线程自然结束

    def registry_actions(self) -> Dict[str, dict]:
        """低代码设计器数据源：动作名 → {description, risk, domain, params}。"""
        if self.registry is None:
            return {}
        out: Dict[str, dict] = {}
        for name in sorted(self.registry.names()):
            e = self.registry.get(name)
            out[name] = {
                "description": getattr(e, "description", ""),
                "risk": getattr(e, "risk", ""),
                "executor_domain": getattr(e, "executor_domain", ""),
                "idempotency": getattr(e, "idempotency", ""),
                "params": getattr(e, "params", None),
                "deprecated": getattr(e, "deprecated", False),
            }
        return out

    def audit_tail(self) -> List[dict]:
        out: List[dict] = []
        for path in self.journal_paths:
            p = Path(path)
            archive = p.with_suffix(p.suffix + ".archive")
            records: List[dict] = []
            for target in (archive, p):
                if target.exists():
                    records.extend(journal_records(target))
            for rec in records:
                if rec.get("kind") not in ("cursor",):
                    rec = dict(rec)
                    rec.setdefault("kind",
                                   "action" if rec.get("action") else rec.get("type", "?"))
                    out.append(rec)
        return out[-self.audit_tail_size:]

    def resolve_task(self, task_id: str, body: dict) -> bool:
        if self._resolve is None:
            return False
        return bool(self._resolve(task_id,
                                  body.get("outcome", "retry"),
                                  body.get("actor", "studio")))

    def serve_forever(self) -> None:
        handler = type("BoundStudio", (StudioHandler,), {"studio": self})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self._httpd.serve_forever()

    def start_background(self) -> int:
        handler = type("BoundStudio", (StudioHandler,), {"studio": self})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        t = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        t.start()
        return self._httpd.server_address[1]

    def shutdown(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()


# ============================ 低代码设计器页面 ============================
_DESIGNER_CSS = """
 body{font-family:-apple-system,sans-serif;margin:0;background:#f4f5f7;color:#222;
      display:flex;flex-direction:column;height:100vh}
 header{background:#1e293b;color:#fff;padding:10px 16px;display:flex;gap:16px;
        align-items:center}
 header a{color:#93c5fd;text-decoration:none;font-size:13px}
 #main{display:flex;flex:1;overflow:hidden}
 .col{padding:12px;overflow-y:auto}
 #listCol{width:220px;border-right:1px solid #ddd;background:#fff}
 #formCol{flex:1;min-width:0}
 #sideCol{width:300px;border-left:1px solid #ddd;background:#fff}
 h3{margin:8px 0;font-size:14px}
 input,textarea,select{font-family:inherit;font-size:13px;padding:4px 6px;
   border:1px solid #ccc;border-radius:4px;box-sizing:border-box;width:100%}
 textarea{font-family:ui-monospace,monospace}
 button{font-size:12px;padding:4px 10px;margin:2px;cursor:pointer;
   border:1px solid #cbd5e1;border-radius:4px;background:#fff}
 button.primary{background:#2563eb;color:#fff;border-color:#2563eb}
 .card{border:1px solid #e2e8f0;border-radius:6px;padding:8px;margin:8px 0;
   background:#fafafa}
 .card .row{display:flex;gap:6px;margin:4px 0}
 .card label{font-size:11px;color:#64748b;display:block;margin-bottom:2px}
 #plist div{padding:6px;cursor:pointer;border-bottom:1px solid #eee;font-size:13px}
 #plist div:hover{background:#eff6ff}
 #plist .invalid{color:#dc2626}
 #catList div{padding:4px 6px;cursor:pointer;font-size:12px;border-radius:4px}
 #catList div:hover{background:#eff6ff}
 .risk{font-size:10px;padding:1px 4px;border-radius:3px;background:#e2e8f0;color:#475569}
 #status{position:fixed;bottom:0;left:0;right:0;padding:6px 16px;font-size:13px;
   background:#0f172a;color:#e2e8f0;min-height:20px}
 #status.err{color:#fca5a5} #status.ok{color:#86efac}
 .meta{display:flex;gap:8px;flex-wrap:wrap}
 .meta>div{flex:1;min-width:120px}
 pre#trace{background:#0f172a;color:#a5f3fc;padding:8px;font-size:12px;
   overflow-x:auto;max-height:260px}
"""

_DESIGNER_HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>APA Designer</title><style>__CSS__</style></head><body>
<header><b>APA Designer</b>
 <span style="font-size:12px;color:#94a3b8">低代码流程编排 · §10.2 模式 B</span>
 <a href="/">← 监控面板</a></header>
<div id="main">
  <div class="col" id="listCol">
    <h3>流程文件</h3>
    <button onclick="newProcess()">＋ 新建</button>
    <div id="plist"></div>
  </div>
  <div class="col" id="formCol">
    <div class="meta">
      <div><label>文件 ID（保存名）</label><input id="p-id" placeholder="po_auto_approval"></div>
      <div><label>触发事件名</label><input id="p-trigger" placeholder="erp.order.approval_requested"></div>
      <div style="max-width:110px"><label>max_actions</label><input id="p-max" type="number" value="50"></div>
    </div>
    <h3>步骤</h3>
    <div>
      <button class="primary" onclick="addStep('')">＋ 动作步骤</button>
      <button onclick="addStep('ai_decision')">＋ AI 决策步骤</button>
      <button onclick="syncToYaml()">表单 → YAML</button>
      <button onclick="yamlToForm()">YAML → 表单</button>
    </div>
    <label style="display:block;margin-top:10px;color:#64748b;font-size:11px">
      YAML（真相源 · 可手改后回填表单）</label>
    <textarea id="yamlBox" rows="12" spellcheck="false"
      style="font-family:ui-monospace,monospace"></textarea>
    <div id="steps"></div>
    <h3>错误处理器（error_handlers）</h3>
    <div id="ehandlers"></div>
    <button onclick="addHandler()">＋ 错误处理器</button>
    <div style="margin-top:12px">
      <button class="primary" onclick="save()">💾 保存（先同步 YAML）</button>
      <span style="color:#94a3b8;font-size:12px">保存会自动执行：表单→YAML→服务端校验→写盘</span>
    </div>
  </div>
  <div class="col" id="sideCol">
    <h3>动作目录（点击添加步骤）</h3>
    <input id="catFilter" placeholder="过滤…" oninput="renderCatalog()">
    <div id="catList"></div>
    <h3>沙盒试运行</h3>
    <div class="card">
      <label>触发事件名</label>
      <input id="t-event" placeholder="erp.order.approval_requested">
      <label style="margin-top:6px">事件数据 (JSON)</label>
      <textarea id="t-data" rows="4">{}</textarea>
      <button class="primary" style="margin-top:8px" onclick="runSandbox()">▶ 试运行（MockERP 沙盒）</button>
    </div>
    <pre id="trace">（运行结果轨迹）</pre>
  </div>
</div>
<div id="status">就绪</div>
<script src="/design.js"></script>
</body></html>"""



_DESIGNER_JS = r"""
"use strict";
let CATALOG = {};
let FORM = null;

const $id = (i) => document.getElementById(i);
function setStatus(msg, cls) {
  const el = $id("status");
  el.textContent = msg;
  el.className = cls || "";
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok && data.error) throw new Error(data.error);
  if (!r.ok && data.errors) throw new Error(data.errors.join("; "));
  return data;
}

// ---- 流程列表 ----
async function refreshList() {
  const items = await api("/api/processes");
  $id("plist").innerHTML = items.map(p =>
    `<div class="${p.valid ? "" : "invalid"}" onclick="openProcess('${p.id}')">` +
    `${esc(p.id)}${p.valid ? "" : " ⚠"}</div>`).join("") ||
    '<div style="color:#94a3b8">（暂无流程，点「＋ 新建」）</div>';
}

async function openProcess(id) {
  try {
    const d = await api("/api/processes/get/" + id);
    $id("yamlBox").value = d.yaml;
    await yamlToForm();
    $id("p-id").value = id;
    setStatus("已加载 " + id, "ok");
  } catch (e) {
    setStatus("加载失败：" + e.message, "err");
  }
}

function blankForm() {
  return { id: "", trigger_name: "", max_actions: 50,
    steps: [{ id: "step_1", type: "", action: "", target: "",
              params_json: "{}", condition: "", output_as: "",
              on_failure_goto: "" }],
    error_handlers: [] };
}
function ensureForm() {
  if (!FORM) FORM = blankForm();
  return FORM;
}

// ---- 渲染 ----
function renderAll() {
  renderMeta(); renderSteps(); renderHandlers();
}
function renderMeta() {
  if (!FORM) return;
  $id("p-id").value = FORM.id || "";
  $id("p-trigger").value = FORM.trigger_name || "";
  $id("p-max").value = FORM.max_actions ?? 50;
}
function stepCard(s, i) {
  const typeSel = `<select class="f-type">
      <option value="" ${s.type === "" ? "selected" : ""}>动作</option>
      <option value="ai_decision" ${s.type === "ai_decision" ? "selected" : ""}>AI 决策</option>
    </select>`;
  return `<div class="card">
    <div class="row">
      <div style="flex:1"><label>步骤 ID</label>
        <input class="f-id" value="${esc(s.id)}"></div>
      <div><label>类型</label>${typeSel}</div>
      <button title="上移" onclick="moveStep(${i},-1)">↑</button>
      <button title="下移" onclick="moveStep(${i},1)">↓</button>
      <button title="删除" onclick="removeStep(${i})">✕</button>
    </div>
    <div class="row">
      <div style="flex:2"><label>动作名（registry）</label>
        <input class="f-action" list="catalog-dl" value="${esc(s.action)}"></div>
      <div style="flex:1"><label>target</label>
        <input class="f-target" value="${esc(s.target || "")}"></div>
    </div>
    <label>参数 (JSON)</label>
    <textarea class="f-params" rows="2">${esc(s.params_json)}</textarea>
    <div class="row">
      <div style="flex:1"><label>condition（原始表达式）</label>
        <input class="f-cond" value="${esc(s.condition)}"></div>
      <div style="flex:1"><label>output_as</label>
        <input class="f-out" value="${esc(s.output_as)}"></div>
      <div style="flex:1"><label>失败跳转 goto</label>
        <input class="f-goto" value="${esc(s.on_failure_goto)}"></div>
    </div>
  </div>`;
}
function handlerCard(h, i) {
  return `<div class="card">
    <div class="row">
      <div style="flex:1"><label>key（goto 目标）</label>
        <input class="h-key" value="${esc(h.key)}"></div>
      <div style="flex:2"><label>action</label>
        <input class="h-action" list="catalog-dl" value="${esc(h.action)}"></div>
      <button onclick="removeHandler(${i})">✕</button>
    </div>
    <label>参数 (JSON)</label>
    <textarea class="h-params" rows="2">${esc(h.params_json)}</textarea>
  </div>`;
}
function renderSteps() {
  ensureForm();
  $id("steps").innerHTML =
    FORM.steps.map((s, i) => stepCard(s, i)).join("") ||
    "<p style='color:#94a3b8;font-size:13px'>（无步骤）</p>";
}
function renderHandlers() {
  ensureForm();
  $id("ehandlers").innerHTML =
    FORM.error_handlers.map((h, i) => handlerCard(h, i)).join("") ||
    "<p style='color:#94a3b8;font-size:13px'>（无错误处理器）</p>";
}

// ---- 表单状态机：DOM ↔ FORM（先收集后变更，防丢输入） ----
function collectForm() {
  ensureForm();
  FORM.id = $id("p-id").value.trim();
  FORM.trigger_name = $id("p-trigger").value.trim();
  FORM.max_actions = parseInt($id("p-max").value || "50", 10) || 50;
  const cards = [...document.querySelectorAll("#steps .card")];
  FORM.steps = cards.map(c => ({
    id: c.querySelector(".f-id").value.trim(),
    type: c.querySelector(".f-type").value,
    action: c.querySelector(".f-action").value.trim(),
    target: c.querySelector(".f-target").value.trim(),
    params_json: c.querySelector(".f-params").value.trim() || "{}",
    condition: c.querySelector(".f-cond").value.trim(),
    output_as: c.querySelector(".f-out").value.trim(),
    on_failure_goto: c.querySelector(".f-goto").value.trim(),
  }));
  for (const st of FORM.steps) {
    try { JSON.parse(st.params_json || "{}"); }
    catch (e) { throw new Error(`步骤 ${st.id || "(未命名)"} 参数不是合法 JSON`); }
  }
  const hcards = [...document.querySelectorAll("#ehandlers .card")];
  FORM.error_handlers = hcards.map(c => ({
    key: c.querySelector(".h-key").value.trim(),
    action: c.querySelector(".h-action").value.trim(),
    params_json: c.querySelector(".h-params").value.trim() || "{}",
  }));
  for (const h of FORM.error_handlers) {
    try { JSON.parse(h.params_json || "{}"); }
    catch (e) { throw new Error(`错误处理器 ${h.key} 参数不是合法 JSON`); }
  }
  return FORM;
}
function guarded(fn) {
  try { fn(); return true; }
  catch (e) { setStatus(e.message, "err"); return false; }
}
function addStep(type) {
  if (!guarded(() => collectForm())) return;
  ensureForm();
  FORM.steps.push({ id: "step_" + (FORM.steps.length + 1), type: type || "",
                    action: "", target: "", params_json: "{}",
                    condition: "", output_as: "", on_failure_goto: "" });
  renderSteps();
}
function removeStep(i) {
  if (!guarded(() => collectForm())) return;
  FORM.steps.splice(i, 1); renderSteps();
}
function moveStep(i, dir) {
  if (!guarded(() => collectForm())) return;
  const j = i + dir;
  if (j < 0 || j >= FORM.steps.length) return;
  [FORM.steps[i], FORM.steps[j]] = [FORM.steps[j], FORM.steps[i]];
  renderSteps();
}
function addHandler() {
  if (!guarded(() => collectForm())) return;
  ensureForm();
  FORM.error_handlers.push({ key: "escalate", action: "", params_json: "{}" });
  renderHandlers();
}
function removeHandler(i) {
  if (!guarded(() => collectForm())) return;
  FORM.error_handlers.splice(i, 1); renderHandlers();
}

// ---- 双向同步 ----
async function syncToYaml() {
  collectForm();
  const d = await api("/api/processes/from-form", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ form: FORM }),
  });
  $id("yamlBox").value = d.yaml;
  setStatus("已同步为 YAML", "ok");
  return d.yaml;
}
async function yamlToForm() {
  const y = $id("yamlBox").value;
  FORM = await api("/api/processes/to-form", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ yaml: y }),
  });
  renderAll();
  setStatus("已从 YAML 加载表单", "ok");
}

// ---- 保存 ----
async function save() {
  try {
    collectForm();
    const yd = await api("/api/processes/from-form", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ form: FORM }),
    });
    $id("yamlBox").value = yd.yaml;
    const res = await api("/api/processes/save", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ id: FORM.id, yaml: yd.yaml }),
    });
    setStatus(`已保存 ${res.process_id}（步骤 ${res.steps}），校验通过`, "ok");
    refreshList();
  } catch (e) {
    setStatus("保存失败：" + e.message, "err");
  }
}

// ---- 动作目录 ----
async function loadCatalog() {
  CATALOG = await api("/api/registry/actions");
  refreshCatalogUI();
}
function refreshCatalogUI() {
  const q = ($id("catFilter").value || "").toLowerCase();
  const names = Object.keys(CATALOG)
    .filter(n => n.toLowerCase().includes(q)).sort();
  const dl = document.getElementById("catalog-dl") ||
             (() => { const d = document.createElement("datalist");
                      d.id = "catalog-dl"; document.body.appendChild(d);
                      return d; })();
  dl.innerHTML = names.map(n => `<option value="${n}">`).join("");
  $id("catList").innerHTML = names.map(n =>
    `<div onclick="insertAction('${n}')" ` +
    `title="${esc(CATALOG[n].description || "")}">${n} ` +
    `<span class="risk">${CATALOG[n].risk}</span></div>`).join("");
}
function insertAction(name) {
  if (!guarded(() => collectForm())) return;
  ensureForm();
  const meta = CATALOG[name] || {};
  FORM.steps.push({
    id: name.replace(/\./g, "_"),
    type: "", action: name, target: "",
    params_json: JSON.stringify(paramsTemplate(meta.params)),
    condition: "", output_as: "", on_failure_goto: "",
  });
  renderSteps();
  setStatus(`已添加 ${name}（按 schema 预填参数模板）`, "ok");
}
function paramsTemplate(schema) {
  const out = {};
  const props = (schema && schema.properties) || {};
  for (const [k, p] of Object.entries(props)) {
    out[k] = p.type === "number" ? 0 : p.type === "boolean" ? false :
             (Array.isArray(p.enum) && p.enum.length ? p.enum[0] : "");
  }
  return out;
}

// ---- 沙盒试运行 ----
async function runSandbox() {
  try { await syncToYaml(); }
  catch (e) { return; }   // 同步失败已提示
  const ev = $id("t-event").value.trim();
  if (!ev) { setStatus("请填写触发事件名", "err"); return; }
  let data = {};
  try { data = JSON.parse($id("t-data").value || "{}"); }
  catch (e) { setStatus("事件数据不是合法 JSON", "err"); return; }
  try {
    const d = await api("/api/processes/test", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ yaml: $id("yamlBox").value, event: ev, data }),
    });
    $id("trace").textContent = JSON.stringify(d, null, 2);
    setStatus(`试运行完成：outcome=${d.outcome}`, "ok");
  } catch (e) {
    setStatus("试运行异常：" + e.message, "err");
  }
}

// ---- 新建 / 初始化 ----
function newProcess() {
  FORM = blankForm();
  renderAll();
  $id("yamlBox").value = "";
  setStatus("新流程：填写 ID 与触发事件，添加步骤后「保存」", "ok");
}

window.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([loadCatalog(), refreshList()]);
  FORM = blankForm(); renderAll();
  setStatus("就绪 —— 从左侧打开流程、点「＋ 新建」或从右侧动作目录添加步骤", "ok");
});
"""


def render_design_page(st) -> str:
    """设计器外壳。数据全部由前端经 API 注入（axiom 15：视图只呈现）。"""
    html = _DESIGNER_HTML.replace("__CSS__", _DESIGNER_CSS)
    return html


def main() -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(prog="studio", description="APA-Studio v1")
    parser.add_argument("--journals", nargs="+", required=True,
                        help="journal 文件或 glob（如 data/*.jsonl）")
    parser.add_argument("--port", type=int, default=8686)
    parser.add_argument("--tenant", default=None, help="仅展示指定租户")
    args = parser.parse_args()
    server = StudioServer(args.journals, port=args.port, tenant=args.tenant)
    print(f"APA-Studio → http://127.0.0.1:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())