"""apa-core: MockERP 参考实现（设计文档 §B.3 问题 4）。

供社区贡献者与测试使用的标准 ERP 模拟服务器（零依赖 stdlib HTTP）。
端点：
    GET  /orders?status=pending        待审批订单列表
    POST /orders/<id>/approve          审批（body: {approver}）
    POST /orders/<id>/reject           驳回（body: {reason_code}）
    POST /invoices                     开票（body: {invoice_no, total, ...}）
    POST /notify                       通知（任意 JSON）
认证：可选 Bearer token（构造时传入；启用后无/错 token → 401）。
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional


class MockERP:
    """内存态 ERP 模拟器。

    erp = MockERP(token="secret"); port = erp.start()
    ... requests.post(f"http://127.0.0.1:{port}/orders/O1/approve",
                      json={"approver": "apa"}, headers={"Authorization": "Bearer secret"})
    erp.stop()
    """

    def __init__(self, *, token: Optional[str] = None,
                 seed_orders: Optional[List[dict]] = None) -> None:
        self.token = token
        self.orders: Dict[str, dict] = {}
        for o in seed_orders or []:
            rec = dict(o)
            rec.setdefault("status", "pending")
            self.orders[rec["id"]] = rec
        self.invoices: List[dict] = []
        self.notifications: List[dict] = []
        self.requests: List[dict] = []   # 全部请求审计 {ts, method, path}
        self._httpd: Optional[ThreadingHTTPServer] = None

    # -- 状态操作（供测试直接断言） --
    def approve(self, order_id: str, approver: str) -> Optional[dict]:
        order = self.orders.get(order_id)
        if order is None:
            return None
        order["status"] = "approved"
        order["approver"] = approver
        order["approved_ms"] = int(time.time() * 1000)
        return order

    def reject(self, order_id: str, reason_code: str) -> Optional[dict]:
        order = self.orders.get(order_id)
        if order is None:
            return None
        order["status"] = "rejected"
        order["reason_code"] = reason_code
        return order

    def pending(self) -> List[dict]:
        return [o for o in self.orders.values() if o.get("status") == "pending"]

    # -- HTTP --
    def start(self, port: int = 0) -> int:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _json(self, code: int, body: Any) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authed(self) -> bool:
                if not outer.token:
                    return True
                auth = self.headers.get("Authorization", "")
                return auth == f"Bearer {outer.token}"

            def do_GET(self):
                outer.requests.append({"ts": time.time(), "method": "GET",
                                       "path": self.path})
                if not self._authed():
                    self._json(401, {"error": "unauthorized"})
                    return
                if self.path.startswith("/orders"):
                    self._json(200, {"items": outer.pending()})
                else:
                    self._json(404, {"error": "not_found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                outer.requests.append({"ts": time.time(), "method": "POST",
                                       "path": self.path, "body_keys":
                                       sorted(body.keys())})
                if not self._authed():
                    self._json(401, {"error": "unauthorized"})
                    return
                parts = [p for p in self.path.split("/") if p]
                if len(parts) == 3 and parts[0] == "orders" \
                        and parts[2] in ("approve", "reject"):
                    fn = outer.approve if parts[2] == "approve" else outer.reject
                    arg = body.get("approver", "") or body.get("reason_code", "")
                    result = fn(parts[1], arg)
                    if result is None:
                        self._json(404, {"error": "order_not_found"})
                    else:
                        self._json(200, result)
                elif parts[:1] == ["invoices"]:
                    body.setdefault("id", f"INV-{len(outer.invoices) + 1}")
                    body["created_ms"] = int(time.time() * 1000)
                    outer.invoices.append(body)
                    self._json(200, body)
                elif parts[:1] == ["notify"]:
                    outer.notifications.append(body)
                    self._json(200, {"ok": True})
                else:
                    self._json(404, {"error": "not_found"})

            def log_message(self, *a):
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self._httpd.server_address[1]

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None