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
    def __init__(self, source: str, session_id: str, transport=None, *,
                 client=None, context_store=None) -> None:
        super().__init__(source, session_id, transport, context_store=context_store)
        if httpx is None:
            raise RuntimeError("httpx is required: pip install httpx")
        self.client = client or httpx.Client(timeout=30.0)

    def start_observation(self) -> None:
        """API 执行器无主动感知，事件由外部注入（如定时任务触发轮询）。"""

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        url = params["url"]
        headers = params.get("headers") or {}
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
                # POC 演示：调用 ERP 审批端点
                resp = self.client.post(
                    f"{url.rstrip('/')}/approve",
                    json={"order_id": order_id, "approver": params.get("approver", "apa_system")},
                    headers=headers,
                )
                return self._result(resp)

            case "erp.order.reject":
                order_id = params["order_id"]
                resp = self.client.post(
                    f"{url.rstrip('/')}/reject",
                    json={"order_id": order_id, "reason_code": params.get("reason_code", "")},
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