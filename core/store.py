"""文件存储：reviews.json（单文件，小规模够用）+ audit.jsonl（只追加）。"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, replace
from time import time

from . import gateway
from .decide import decide
from .models import NEEDS_REVIEW, ReviewItem, ReviewRecord, new_id


def _blob_threshold() -> int:
    try:
        return int(os.environ.get("COD_BLOB_THRESHOLD", "2048"))
    except ValueError:
        return 2048


class ReviewStore:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.blobs_dir = os.path.join(data_dir, "blobs")
        os.makedirs(self.blobs_dir, exist_ok=True)
        self.db_path = os.path.join(data_dir, "reviews.json")
        self.audit_path = os.path.join(data_dir, "audit.jsonl")
        self._db: dict = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.db_path):
            return {}
        with open(self.db_path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.data_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self._db, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.db_path)

    def _blob_path(self, ref: str) -> str:
        # ref 形如 ctx_<id>_body；只允许安全字符，防路径穿越
        if not re.fullmatch(r"ctx_[A-Za-z0-9_]+\.body", ref):
            raise ValueError(f"bad ref: {ref}")
        return os.path.join(self.blobs_dir, ref + ".txt")

    def _spill_body(self, item_id: str, body: str) -> str:
        """正文超阈值则落 blobs，返回引用（CoD）；否则返回空串。"""
        if len(body) <= _blob_threshold():
            return ""
        ref = f"ctx_{item_id}.body"
        fd, tmp = tempfile.mkstemp(dir=self.blobs_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, self._blob_path(ref))
        return ref

    def context_get(self, ref: str, fields: list) -> dict:
        """CoD 真读写：按字段取引用对象；禁 ["*"]（CoD-2），读走审计。"""
        if not isinstance(fields, list) or not fields:
            raise ValueError("fields must be a non-empty list")
        if "*" in fields:
            raise ValueError('fields ["*"] forbidden (CoD-2)')
        with open(self._blob_path(ref), encoding="utf-8") as f:
            obj = {"body": f.read()}
        unknown = [x for x in fields if x not in obj]
        if unknown:
            raise ValueError(f"unknown fields: {unknown}")
        out = {k: obj[k] for k in fields}
        gateway.audit_log(self.audit_path, {
            "event": "context.get", "ref": ref, "fields": fields})
        return {"ref": ref, "data": out}

    def submit(self, kind: str, title: str, body: str, meta: dict | None = None,
               on_progress=None) -> ReviewRecord:
        """on_progress(type, payload)：accepted → running → terminal 进度事件。

        只走 SSE，不进审计（审计保持终态-only）。调用方无回调即静默。
        """
        item = ReviewItem(new_id("rev"), kind, title, body, meta or {})

        def emit(ptype: str):
            if on_progress:
                on_progress(ptype, {"id": item.id, "ts": int(time() * 1000)})

        emit("accepted")
        emit("running")
        decision = decide(item)  # 决策看全文；落盘只留引用（CoD）
        final_action, via = gateway.route(decision.action, decision.confidence)
        ok, verdict = gateway.validate_action(final_action, {"review_id": item.id})
        if not ok:  # 网关内动作必须合法，否则是代码 bug。
            # 不用 assert：`python -O` 会把真实门禁一起摘掉。
            raise RuntimeError(f"gateway rejected internal action: {verdict}")
        state = {"review.approve": "approved", "review.reject": "rejected"}.get(
            final_action, "pending")
        body_ref = self._spill_body(item.id, body)
        stored_item = replace(item, body="" if body_ref else body, body_ref=body_ref)
        rec = ReviewRecord(stored_item, decision, state)
        if state == "pending":
            decision.action = NEEDS_REVIEW
        progress = ["accepted", "running", "terminal"]
        self._db[item.id] = {
            "item": asdict(stored_item),
            "decision": asdict(decision),
            "state": state,
            "via": via,
            "verdict": verdict,
            "progress": progress,
            "terminal_at": int(time() * 1000),
            "resolved_by": "",
            "resolved_outcome": "",
        }
        emit("terminal")
        gateway.audit_log(self.audit_path, {
            "event": "review.submitted",
            "review_id": item.id, "kind": kind,
            "action": final_action, "via": via,
            "confidence": decision.confidence, "engine": decision.engine,
            "body_ref": body_ref or None,
        })
        self._save()
        return rec

    def resolve(self, review_id: str, outcome: str, actor: str) -> dict:
        if review_id not in self._db:
            raise KeyError(f"review not found: {review_id}")
        if outcome not in ("approve", "reject"):
            raise ValueError("outcome must be approve|reject")
        rec = self._db[review_id]
        if rec["state"] != "pending":
            raise ValueError(f"already resolved: {rec['state']}")
        rec["state"] = "approved" if outcome == "approve" else "rejected"
        rec["resolved_by"] = actor
        rec["resolved_outcome"] = outcome
        gateway.audit_log(self.audit_path, {
            "event": "human.task.completed",
            "review_id": review_id, "outcome": outcome, "actor": actor,
        })
        self._save()
        return rec

    def queue(self, state: str = "") -> list:
        return [r for r in self._db.values() if not state or r["state"] == state]
