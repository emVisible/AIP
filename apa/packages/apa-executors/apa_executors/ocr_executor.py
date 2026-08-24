"""apa-executors: OCR 文字识别执行器（可插拔后端接入点）。

动作域：ocr.*
后端策略：
  - mock      ：离线测试后端（无网络依赖，返回固定文本）
  - http_ocr  ：通用 HTTP OCR API —— POST {endpoint} 携带 base64 图片，
                凭据经 Vault 注入请求头（C4），兼容多数云端 OCR 服务
输入：image_path（本地文件）或 image_b64（内联）
输出：{text, confidence?, raw}，文本同时写入 ContextStore

凭据注入与 api.http 同款：params.auth = {"vault": name} / {"env": VAR}
"""
from __future__ import annotations

import base64
import json
import os
import time as _t
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from apa_sdk.executor_base import AIPExecutor


class OCRExecutor(AIPExecutor):
    """OCR 接入点执行器。"""

    def __init__(self, source: str, session_id: str, transport=None, *,
                 context_store=None, vault=None) -> None:
        super().__init__(source, session_id, transport,
                         context_store=context_store)
        self.vault = vault

    def start_observation(self) -> None:
        pass

    # ---- 凭据（C4：机密只在执行器内解析）-----------------------------------
    def _resolve_headers(self, params: dict) -> Dict[str, str]:
        headers: Dict[str, str] = dict(params.get("headers") or {})
        auth = params.get("auth")
        if auth and self.vault is not None:
            from apa_core.vault import VaultManager
            headers = VaultManager(self.vault).inject_headers(headers, auth)
        return headers

    @staticmethod
    def _load_image_b64(params: dict) -> str:
        b64: Optional[str] = params.get("image_b64")
        if b64:
            return b64
        path = params.get("image_path")
        if not path:
            raise ValueError("image_path or image_b64 required")
        return base64.b64encode(Path(path).read_bytes()).decode()

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        if name == "ocr.extract":
            backend = params.get("backend", "mock")
            try:
                if backend == "mock":
                    return self._mock(params)
                if backend == "http_ocr":
                    return self._http_ocr(params)
                return False, {"code": f"unknown backend {backend!r}"}
            except FileNotFoundError as e:
                return False, {"code": "file_not_found", "detail": str(e)}
            except Exception as e:  # noqa: BLE001
                return False, {"code": type(e).__name__, "detail": str(e)}

        if name == "ocr.screen_text":
            return self._screen_text(params)
        if name == "if.text_on_screen":
            from . import screen_ocr as so

            try:
                hit = so.locate_text(
                    str(params.get("text", "")),
                    region=params.get("region"),
                    contains=params.get("contains", True))
            except RuntimeError as e:
                return False, {"code": "capture_denied", "detail": str(e)}
            return True, {"matched": hit is not None,
                          **({"bounds": hit["bounds"]}
                             if hit else {})}

        if name == "ocr.wait_text":
            return self._wait_text(params)

        return False, {"code": "action_not_supported_by_executor"}

    def _screen_text(self, params: dict) -> Tuple[bool, dict]:
        """屏幕区域 OCR（Apple Vision，需屏幕录制权限）。"""
        try:
            from . import screen_ocr as so
        except RuntimeError as e:
            return False, {"code": "dependency_missing", "detail": str(e)}
        try:
            region = params.get("region")
            hits = so.ocr_screen(region, lang=params.get("language", "zh-Hans"),
                                 accurate=params.get("accurate", True))
        except RuntimeError as e:
            return False, {"code": "capture_denied", "detail": str(e)}
        out = {"hits": hits, "count": len(hits)}
        ref_key = params.get("output_context")
        if ref_key and self.context_store is not None:
            ref = self.context_store.make_ref(self.peer.session_id, ref_key)
            self.context_store.put(ref, out)
        return True, out

    # ---- 后端实现 -----------------------------------------------------------

    def _mock(self, params: dict) -> Tuple[bool, dict]:
        """离线后端：返回图片文件名作为文本（测试用）。"""
        text = f"[mock-ocr] {Path(params.get('image_path', 'inline')).name}"
        out = {"text": text, "backend": "mock", "confidence": 1.0}
        self._store(out, params)
        return True, out

    def _http_ocr(self, params: dict) -> Tuple[bool, dict]:
        """通用 HTTP OCR：POST endpoint {image_b64, language} → JSON。

        兼容约定：响应取 resp.text / resp.data.text /
        resp.choices[0].message.content 三者之一。
        """
        import httpx

        endpoint = params["endpoint"]
        image_b64 = self._load_image_b64(params)
        headers = self._resolve_headers(params)
        headers.setdefault("Content-Type", "application/json")

        payload: Dict[str, Any] = {
            "image_b64": image_b64,
            "language": params.get("language", "chs"),
        }
        timeout = float(os.environ.get("APA_OCR_TIMEOUT", "30"))
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(endpoint,
                               content=json.dumps(payload),
                               headers=headers)
            resp.raise_for_status()
            data = resp.json()

        text = ""
        if isinstance(data, str):
            text = data
        elif isinstance(data, dict):
            if isinstance(data.get("text"), str):
                text = data["text"]
            elif isinstance(data.get("data"), dict):
                text = str(data["data"].get("text", ""))
            elif isinstance(data.get("choices"), list) and data["choices"]:
                msg = data["choices"][0].get("message") or {}
                text = str(msg.get("content", ""))
        out = {
            "text": text,
            "backend": "http_ocr",
            "raw_keys": (list(data.keys())
                         if isinstance(data, dict) else []),
        }
        self._store(out, params)
        return True, out

    def _wait_text(self, params: dict) -> Tuple[bool, dict]:
        """轮询等待屏幕文字出现（影刀「等待文字」对标）。"""
        from . import screen_ocr as so

        target = str(params.get("text", ""))
        if not target:
            return False, {"code": "missing_param", "detail": "text"}
        timeout_s = min(float(params.get("timeout_s", 10.0)), 120.0)
        interval_s = max(float(params.get("interval_s", 0.5)), 0.1)
        region = params.get("region")

        deadline = _t.monotonic() + timeout_s
        last_err: Optional[str] = None
        while _t.monotonic() < deadline:
            try:
                hit = so.locate_text(
                    target, region=region,
                    contains=params.get("contains", True),
                    min_confidence=float(
                        params.get("min_confidence", 0.3)))
            except RuntimeError as e:
                last_err = str(e)[:80]      # 屏幕录制权限等
                hit = None
            if hit is not None:
                out = {"found": True, "bounds": hit["bounds"],
                       "text": hit["text"],
                       "confidence": hit["confidence"]}
                ref = params.get("output_context")
                if ref and self.context_store is not None:
                    r2 = self.context_store.make_ref(self.peer.session_id,
                                                     str(ref))
                    self.context_store.put(r2, out)
                return True, out
            _t.sleep(interval_s)

        return False, {"code": "text_timeout",
                       "text": target,
                       "detail": last_err or "not found"}

    def _store(self, out: dict, params: dict) -> None:
        ref_key = params.get("output_context")
        if ref_key and self.context_store is not None:
            ref = self.context_store.make_ref(self.peer.session_id, ref_key)
            self.context_store.put(ref, out)