"""apa-core: Session 持久化（设计文档 §10.1）。

append-only JSONL 日志：状态迁移 / 游标 / 人工任务 / 终态。
recover() 重放日志重建 Gateway 状态（游标精确恢复，断线不丢状态 — AIP I3）。
终态 Session 释放资源由 release_expired 实现（默认 30 分钟，可配置）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from aip import now_ms


class SessionJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: List[dict] = []

    def record(self, kind: str, **fields) -> dict:
        rec = {"kind": kind, "ts": now_ms(), **fields}
        self._records.append(rec)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def all(self) -> List[dict]:
        return list(self._records)


def load_journal(path: str | Path) -> List[dict]:
    """读取 JSONL 日志（文件不存在返回空）。"""
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # 容忍尾部半行
    return out


def recover(
    session_id: str,
    journal_path: str | Path,
    *,
    registry=None,
    policy=None,
    identities: Optional[Dict[str, str]] = None,
    audit=None,
    clock=None,
    process_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """从日志重建 EmbeddedGateway（状态/游标/人工任务），继续追加同一日志。

    用法：
        gw = recover("s_001", "data/s_001.jsonl", registry=..., identities=...)
        gw.run()   # 各端点以 hello(cursors) 重连后精确续传
    """
    from .embedded import EmbeddedGateway

    records = load_journal(journal_path)
    journal = SessionJournal(journal_path)
    journal._records = list(records)

    gw = EmbeddedGateway(
        session_id,
        registry=registry,
        policy=policy,
        identities=identities,
        audit=audit,
        clock=clock,
        process_id=process_id,
        tenant_id=tenant_id,
        journal=journal,
    )
    g = gw.gateway

    cursors: Dict[str, int] = {}
    tasks: Dict[str, dict] = {}
    resolved: set = set()
    state = "INITIALIZING"
    outcome = None
    for r in records:
        kind = r.get("kind")
        if kind == "cursor":
            cursors[r["source"]] = max(cursors.get(r["source"], 0), r["seq"])
            g.session.receiver.apply_seq(session_id, r["source"], r["seq"])
        elif kind == "state":
            state = r["to"]
        elif kind == "task":
            if r.get("status") == "resolved":
                resolved.add(r["task_id"])
            else:
                tasks[r["task_id"]] = {
                    "task_id": r["task_id"], "status": "open",
                    "task_type": r.get("task_type", "exception"),
                }
        elif kind == "outcome":
            outcome = r.get("outcome")

    # 状态机恢复
    sm = g.sm
    if state not in ("INITIALIZING",):
        sm.force_state(state)
    sm.record.cursors.update(cursors)
    # 未完成的人工任务 → 重新挂起（§4.3：Bot 进程无需保持连接）
    open_tasks = [tid for tid in tasks if tid not in resolved]
    if open_tasks:
        for tid in open_tasks:
            g.human.restore(tasks[tid])
        for tid in open_tasks:
            if tid not in sm.record.human_tasks:
                sm.record.human_tasks.append(tid)
        if sm.state == "RUNNING":
            sm.force_state("SUSPENDED")
    if outcome:
        sm.record.outcome = outcome
    return gw


def release_expired(journal_path: str | Path, ttl_minutes: int = 30) -> int:
    """终态 Session 资源释放（§10.1：终态 30 分钟后释放）。返回释放的会话数。

    POC 实现：把超过 TTL 的日志归档为 <path>.archive。<new> 文件并清空原文件。
    """
    import time
    p = Path(journal_path)
    records = load_journal(p)
    if not records:
        return 0
    terminal = {"COMPLETED", "FAILED", "CANCELLED"}
    last_state_ts: Dict[str, float] = {}
    sessions: Dict[str, list] = {}
    for r in records:
        sessions.setdefault(r.get("session", ""), []).append(r)
    released = 0
    cutoff = time.time() * 1000 - ttl_minutes * 60 * 1000
    keep: List[dict] = []
    archive: List[dict] = []
    for sid, rs in sessions.items():
        states = [r for r in rs if r.get("kind") == "state"]
        is_terminal = bool(states) and states[-1].get("to") in terminal
        # 以终态时间戳为释放基准（后续 cursor 等记录不影响判定）
        ts = states[-1].get("ts", 0) if is_terminal else 0
        if is_terminal and ts and ts < cutoff:
            archive.extend(rs)
            released += 1
        else:
            keep.extend(rs)
    if archive:
        with open(p.with_suffix(p.suffix + ".archive"), "a", encoding="utf-8") as fh:
            for r in archive:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(p, "w", encoding="utf-8") as fh:
            for r in keep:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return released