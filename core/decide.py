"""Decision 入口（薄层）：级联 + 主引擎名。实现见 engines.py。

本文件保持 stdlib only：laya/torch 重依赖只活在 vendor/laya_sidecar 进程里，
Jev 走云端 HTTPS。历史函数名保留兼容（heuristic_decide 等）。
"""
from __future__ import annotations

from .engines import (  # noqa: F401
    AUTO_THRESHOLD,
    availability,
    cascade,
    heuristic_decide,
)
from .models import ReviewItem  # noqa: F401


def decide(item: ReviewItem, questions: dict | None = None):
    """按 ENGINE_ORDER 级联，首个 Decision 胜出，heuristic 永远兜底。"""
    return cascade(item, questions)


def engine_name() -> str:
    """主模型引擎（状态栏/统计用，不跑推理）：laya:sidecar/jev/heuristic。"""
    return availability()["primary"]
