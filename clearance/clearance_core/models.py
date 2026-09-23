"""Clearance 通用审核网关 — 数据模型（stdlib only）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from uuid import uuid4


AUTO_APPROVE = "review.approve"
AUTO_REJECT = "review.reject"
NEEDS_REVIEW = "human.task.create"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass
class ReviewItem:
    id: str
    kind: str  # article | comment | product | ticket | expense | other
    title: str = ""
    body: str = ""
    meta: dict = field(default_factory=dict)
    ts: int = field(default_factory=lambda: int(time() * 1000))

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}".strip()


@dataclass
class Decision:
    action: str  # review.approve | review.reject | human.task.create
    confidence: float
    engine: str  # laya:sidecar | heuristic
    reasons: list = field(default_factory=list)
    risk: str = "L1"
    latency_ms: int = -1  # 端到端判定耗时（sidecar 实测；heuristic 为 -1）
    route_model: str = ""  # laya 路由到的 checkpoint（english/multilingual）


@dataclass
class ReviewRecord:
    item: ReviewItem
    decision: Decision
    state: str  # approved | rejected | pending
    resolved_by: str = ""
    resolved_outcome: str = ""
