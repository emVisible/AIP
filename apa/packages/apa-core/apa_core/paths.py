"""APA 数据路径单一真相源（架构宪法 §三）。

所有数据目录经此解析；env `APA_DATA_DIR` 可整体重定向
（默认 `data/`，与历史布局兼容）。业务代码禁止散写字符串路径。
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["data_root", "sessions_dir", "spills_dir", "sandbox_dir",
           "processes_dir"]


def data_root() -> Path:
    env = os.environ.get("APA_DATA_DIR")
    return Path(env) if env else Path("data")


def sessions_dir() -> Path:
    return data_root() / "sessions"


def spills_dir() -> Path:
    return data_root() / "spills"


def sandbox_dir() -> Path:
    return data_root() / "sandbox"


def processes_dir() -> Path:
    return data_root() / "processes"
