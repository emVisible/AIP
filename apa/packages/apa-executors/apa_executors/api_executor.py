"""apa-executors: APIExecutor（设计文档 §5.1/§5.4 对应 API 场景）。

REST/SOAP/gRPC 服务。无感知层，直接结构化。凭据从 Vault 注入
（POC：从 params 或环境变量读取，不通过 AIP 协议传输，C4）。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from apa_sdk import AIPExecutor, ExecutorPreconditionError

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class APIExecutor(AIPExecutor):
    """凭据注入层（C4）：params.auth 携带引用（{"vault": name} / {"env": VAR}），
    机密在本执行器内由 Vault 解析并注入请求头，绝不进入 AIP 协议。"""

    def __init__(self, source: str, session_id: str, transport=None, *,
                 client=None, context_store=None, base_url: str = "",
                 vault=None) -> None:
        super().__init__(source, session_id, transport, context_store=context_store)
        if httpx is None:
            raise RuntimeError("httpx is required: pip install httpx")
        self.client = client or httpx.Client(timeout=30.0)
        self.base_url = base_url.rstrip("/")
        self._polled_ids: set = set()
        self.vault = vault

    def _resolve_headers(self, params: dict) -> dict:
        headers = dict(params.get("headers") or {})
        auth = params.get("auth")
        if auth and self.vault is not None:
            from apa_core.vault import VaultManager
            headers = VaultManager(self.vault).inject_headers(headers, auth)
        return headers

    def start_observation(self) -> None:
        """API 执行器无主动感知，事件由外部注入（如定时任务触发轮询）。"""

    def poll_once(self, *, event_name: str, url: str,
                  headers: Optional[dict] = None,
                  item_to_data=None) -> int:
        """轮询一次端点 → 新资源以语义事件发出（§B.3 轮询模式）。

        event_name 如 "erp.invoice.received"；去重键取每项的 id 字段。
        返回新发出的事件数。
        """
        resp = self.client.get(url, headers=headers or {})
        if resp.status_code >= 400:
            return 0
        try:
            items = resp.json()
            if isinstance(items, dict):
                items = items.get("items", [])
        except Exception:
            return 0
        count = 0
        for item in items:
            key = str(item.get("id", "")) if isinstance(item, dict) else str(item)
            if key in self._polled_ids:
                continue
            self._polled_ids.add(key)
            data = item_to_data(item) if item_to_data else (
                item if isinstance(item, dict) else {"value": item})
            ref = self.put_context(f"api_{abs(hash(key)) % 100000}", data)
            payload = dict(data)
            payload.setdefault("context", ref)
            self.emit(event_name, payload)
            count += 1
        return count

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        url = params.get("url", "")
        headers = self._resolve_headers(params)
        match name:
            case "api.http.get":
                resp = self.client.get(url, headers=headers)
                return self._result(resp)

            case "api.http.post":
                resp = self.client.post(url, json=params.get("json"), headers=headers)
                return self._result(resp)

            case "api.http.put":
                resp = self.client.put(url, json=params.get("json"), headers=headers)
                return self._result(resp)

            case "api.http.patch":
                resp = self.client.patch(url, json=params.get("json"), headers=headers)
                return self._result(resp)

            case "api.http.delete":
                resp = self.client.delete(url, headers=headers)
                return self._result(resp)

            case "erp.order.approve":
                order_id = params["order_id"]
                base = (self.base_url or url).rstrip("/")
                if not base:
                    return False, {"code": "endpoint_not_configured"}
                resp = self.client.post(
                    f"{base}/orders/{order_id}/approve",
                    json={"approver": params.get("approver", "apa_system")},
                    headers=headers,
                )
                return self._result(resp)

            case "erp.order.reject":
                order_id = params["order_id"]
                base = (self.base_url or url).rstrip("/")
                if not base:
                    return False, {"code": "endpoint_not_configured"}
                resp = self.client.post(
                    f"{base}/orders/{order_id}/reject",
                    json={"reason_code": params.get("reason_code", "")},
                    headers=headers,
                )
                return self._result(resp)

            case "erp.invoice.create":
                # base_url 来自执行器配置（凭据/端点不经协议，C4）
                resp = self.client.post(
                    f"{self.base_url}/invoices",
                    json={k: params[k] for k in ("invoice_no", "date", "vendor", "total")
                          if k in params},
                    headers=headers,
                )
                return self._result(resp)

            case _:
                return False, {"code": "action_not_supported_by_executor"}

    def _result(self, resp) -> Tuple[bool, dict]:
        try:
            body = resp.json()
        except Exception:
            body = {"text": resp.text[:1024]}
        if resp.status_code >= 400:
            return False, {"code": f"http_{resp.status_code}", "detail": body}
        return True, {"status_code": resp.status_code, "body": body}

    def close(self) -> None:
        self.client.close()