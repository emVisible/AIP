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
    body_ref: str = ""  # 非空即引用：正文存 blobs/，本字段为空（CoD）

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}".strip()


@dataclass
class Decision:
    action: str  # review.approve | review.reject | human.task.create
    confidence: float
    engine: str  # rules | laya:sidecar | jev | heuristic
    reasons: list = field(default_factory=list)
    # 风险等级不在此声明：它是「能力」的属性，唯一权威是 gateway.REGISTRY（C3）。
    # 曾有一个 risk 字段随 Decision 传来，与注册表同语义不同值（approve 报 L1、注册表 L2）。
    latency_ms: int = -1  # 端到端判定耗时（实测；heuristic/rules 为 -1）
    route_model: str = ""  # 路由到的 checkpoint / 云端模型版本
    usage: dict = field(default_factory=dict)  # 云端计费：{input_tokens, output_tokens}


@dataclass
class ReviewRecord:
    item: ReviewItem
    decision: Decision
    state: str  # approved | rejected | pending
    resolved_by: str = ""
    resolved_outcome: str = ""
