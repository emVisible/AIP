"""apa-core: Session 状态机（设计文档 §10.1）。

状态：INITIALIZING → RUNNING ⇄ SUSPENDED/RECOVERING/PAUSED → COMPLETING
     → COMPLETED | FAILED | CANCELLED（终态）。

状态机在 Gateway 侧持有（C7：Decision Engine 不持有任何执行状态）。
Session 记录每个 Executor 的游标（cursor），断线重连后从 cursor 精确恢复。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# 终态
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}

VALID_TRANSITIONS = {
    "INITIALIZING": {"RUNNING", "FAILED"},
    "RUNNING": {"SUSPENDED", "RECOVERING", "PAUSED", "COMPLETING", "FAILED", "CANCELLING"},
    "SUSPENDED": {"RUNNING", "FAILED", "CANCELLING"},
    "RECOVERING": {"RUNNING", "FAILED"},
    "PAUSED": {"RUNNING", "FAILED"},
    "COMPLETING": {"COMPLETED", "FAILED"},
    "CANCELLING": {"CANCELLED", "FAILED"},
}


class IllegalStateTransition(ValueError):
    pass


@dataclass
class SessionRecord:
    session_id: str
    process_id: Optional[str] = None
    tenant_id: Optional[str] = None
    state: str = "INITIALIZING"
    cursors: Dict[str, int] = field(default_factory=dict)
    human_tasks: List[str] = field(default_factory=list)  # 挂起该 session 的任务
    connected: Dict[str, bool] = field(default_factory=dict)  # executor_id -> bool
    error: Optional[str] = None
    outcome: Optional[str] = None
    created_ms: int = 0
    updated_ms: int = 0
    stats: Dict[str, int] = field(default_factory=lambda: {
        "events": 0, "actions": 0, "results": 0, "errors": 0,
    })

    def transition(self, to: str) -> None:
        if self.state in TERMINAL:
            raise IllegalStateTransition(f"{self.state} is terminal")
        if to not in VALID_TRANSITIONS[self.state]:
            raise IllegalStateTransition(f"invalid transition {self.state} -> {to}")
        self.state = to

    def register_executor(self, executor_id: str, cursor: int = 0) -> None:
        self.cursors[executor_id] = cursor
        self.connected[executor_id] = True

    def disconnect(self, executor_id: str) -> None:
        if executor_id in self.connected:
            self.connected[executor_id] = False

    def reconnect(self, executor_id: str, cursor: int) -> None:
        self.connected[executor_id] = True
        if cursor > self.cursors.get(executor_id, 0):
            self.cursors[executor_id] = cursor

    def is_terminal(self) -> bool:
        return self.state in TERMINAL


class SessionStateMachine:
    """持有 SessionRecord 并驱动状态迁移。"""

    def __init__(self, session_id: str, *, process_id: str | None = None,
                 tenant_id: str | None = None, clock=None) -> None:
        self.clock = clock
        now = clock.now_ms() if clock else 0
        self.record = SessionRecord(
            session_id=session_id, process_id=process_id, tenant_id=tenant_id,
            created_ms=now, updated_ms=now,
        )

    @property
    def state(self) -> str:
        return self.record.state

    def _touch(self) -> None:
        if self.clock:
            self.record.updated_ms = self.clock.now_ms()

    def transition(self, to: str) -> str:
        self.record.transition(to)
        self._touch()
        return self.record.state

    def start(self) -> None:
        if self.state == "INITIALIZING":
            self.transition("RUNNING")

    # --- 生命周期事件 ----------------------------------------------------------
    def executor_ready(self, executor_id: str, cursor: int = 0) -> None:
        self.record.register_executor(executor_id, cursor)
        self._touch()

    def executor_lost(self, executor_id: str) -> None:
        self.record.disconnect(executor_id)
        self._touch()

    def executor_reconnected(self, executor_id: str, cursor: int) -> None:
        self.record.reconnect(executor_id, cursor)
        self._touch()

    # --- 人工干预 ---------------------------------------------------------------
    def suspend_for_human(self, task_id: str) -> None:
        self.record.human_tasks.append(task_id)
        self.transition("SUSPENDED")

    def resume_after_human(self, task_id: Optional[str] = None) -> None:
        if task_id and task_id in self.record.human_tasks:
            self.record.human_tasks.remove(task_id)
        if not self.record.human_tasks and self.state == "SUSPENDED":
            self.transition("RUNNING")

    # --- 收尾 -------------------------------------------------------------------
    def complete(self, outcome: str = "success") -> None:
        if self.state in ("RUNNING", "SUSPENDED", "PAUSED"):
            self.transition("COMPLETING")
        if self.state == "COMPLETING":
            self.transition("COMPLETED")
        self.record.outcome = outcome
        self._touch()

    def fail(self, reason: str) -> None:
        if self.state not in TERMINAL:
            self.transition("FAILED")
            self.record.error = reason
            self._touch()

    def cancel(self) -> None:
        if self.state not in TERMINAL:
            if self.state != "CANCELLING":
                self.transition("CANCELLING")
            self.transition("CANCELLED")
            self.record.outcome = "cancelled"
            self._touch()

    def stats_bump(self, kind: str) -> None:
        if kind in self.record.stats:
            self.record.stats[kind] += 1

    def summary(self) -> dict:
        return {
            "session_id": self.record.session_id,
            "process_id": self.record.process_id,
            "state": self.record.state,
            "cursors": dict(self.record.cursors),
            "connected": dict(self.record.connected),
            "human_tasks": list(self.record.human_tasks),
            "error": self.record.error,
            "outcome": self.record.outcome,
            "stats": dict(self.record.stats),
        }