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
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional

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
        elif self.path == "/api/analytics":
            from .analytics import summarize
            data = summarize(st.journal_paths, tenant=st.tenant)
            self._send(json.dumps(data, ensure_ascii=False).encode(),
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
                 resolve_task=None) -> None:
        # 惰性展开：journal 文件可能在服务启动后才产生（HITL 交互场景）
        self.journal_patterns = list(journals)
        self.port = port
        self.audit_tail_size = audit_tail_size
        self.tenant = tenant          # 多租户过滤（§12.1）
        # token 配置后所有请求须带 Authorization: Bearer <token>（§12.1）
        self.token = token
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