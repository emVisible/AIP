"""apa-core: append-only 审计日志（设计文档 §12.3）。

写模式为 append-only（JSONL），支持 WORM 存储配置。
记录 action 审批决策、凭据扫描结果、AI 成本、执行耗时。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from aip import now_ms


class AuditService:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self.path = Path(path) if path else None
        self._fh = None
        self._lock = threading.Lock()
        self.events: List[dict] = []

    def _open(self) -> None:
        if self.path and self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8")

    def _append(self, record: dict) -> None:
        self._open()
        if self._fh is not None:
            self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._fh.flush()
        self.events.append(record)

    # --- 记录类型 ---------------------------------------------------------------
    def log_action(
        self,
        *,
        audit_id: Optional[str],
        session_id: str,
        process_id: Optional[str],
        tenant_id: Optional[str],
        action_id: str,
        action_name: str,
        source: str,
        executor: str,
        in_reply_to_event: Optional[str],
        verdict: str,
        risk_level: str,
        policy_rules_applied: List[str],
        credential_scan: str,
        params_audit: Dict[str, Any],
        mask_fields: Optional[List[str]] = None,
        ai: Optional[Dict[str, Any]] = None,
        outcome: Optional[Dict[str, Any]] = None,
        event_ts: Optional[int] = None,
    ) -> dict:
        params = dict(params_audit)
        for f in mask_fields or []:
            if f in params:
                params[f] = "***"
        record = {
            "audit_id": audit_id or f"aud_{now_ms()}",
            "schema_version": "1.0",
            "session": {
                "id": session_id,
                "process_id": process_id,
                "tenant_id": tenant_id,
                "triggered_by": None,
            },
            "action": {
                "id": action_id,
                "name": action_name,
                "source": source,
                "executor": executor,
                "in_reply_to_event": in_reply_to_event,
            },
            "security": {
                "verdict": verdict,
                "risk_level": risk_level,
                "policy_rules_applied": policy_rules_applied,
                "credential_scan": credential_scan,
            },
            "params_audit": params,
            "outcome": outcome or {"status": "pending", "ts_start": now_ms()},
            "ai": ai or {},
            "ts": event_ts or now_ms(),
        }
        self._append(record)
        return record

    def log_event(self, session_id: str, source: str, name: str,
                  data_size: int, ts: Optional[int] = None) -> dict:
        record = {
            "audit_id": f"evt_{now_ms()}",
            "type": "event",
            "session": session_id,
            "source": source,
            "name": name,
            "data_size_bytes": data_size,
            "cod_ok": data_size <= 4096,  # CoD-1
            "ts": ts or now_ms(),
        }
        self._append(record)
        return record

    def log_error(self, session_id: str, code: str, detail: str,
                  ts: Optional[int] = None) -> dict:
        record = {
            "audit_id": f"err_{now_ms()}",
            "type": "error",
            "session": session_id,
            "code": code,
            "detail": detail,
            "ts": ts or now_ms(),
        }
        self._append(record)
        return record

    def read_all(self) -> List[dict]:
        return list(self.events)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None