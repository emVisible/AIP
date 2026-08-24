"""apa-core: 环境配置加载（零依赖 .env 支持，DeepSeek API 为默认底座）。

约定：
    · 仓库根或当前目录的 .env 自动发现并加载（幂等，不覆盖已有环境变量）
    · 模板见 .env.example —— 复制为 .env 后填入真实 Key

优先级：已存在环境变量 > .env 文件。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

_LOADED_FROM: Optional[str] = None


def parse_env_file(path: Path) -> Dict[str, str]:
    """解析 KEY=VALUE 行；支持 # 注释、export 前缀、引号包裹。"""
    out: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 占位值防御（axiom 1.4）：模板 .env 常见 `KEY=# 必填…`。
        # 该值是注释残片并非密钥 —— 入 environ 会固化并遮蔽一切
        # 后续配置源（真实 Key / 测试注入）。仅丢弃 # 开头占位；
        # 显式空串保留原语义（env_first 视为未设置）。
        if value.startswith("#"):
            continue
        out[key] = value
    return out


def find_dotenv(start: Optional[Path] = None,
                max_up: int = 6) -> Optional[Path]:
    """自 start（默认 cwd）向上查找 .env，最多 max_up 层。"""
    cur = (Path(start) if start else Path.cwd()).resolve()
    for _ in range(max_up):
        candidate = cur / ".env"
        if candidate.is_file():
            return candidate
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def load_dotenv(path: Optional[Path] = None, *,
                override: bool = False) -> Dict[str, str]:
    """加载 .env 到 os.environ（默认不覆盖已有值）。返回实际载入的键值。"""
    global _LOADED_FROM
    target = path or find_dotenv()
    if target is None or not Path(target).is_file():
        return {}
    loaded: Dict[str, str] = {}
    for key, value in parse_env_file(Path(target)).items():
        if override or not os.environ.get(key):
            os.environ[key] = value
            loaded[key] = value
    _LOADED_FROM = str(target)
    return loaded


def ensure_env_loaded() -> bool:
    """幂等入口：供各组件构造器调用。返回是否已完成一次文件加载。"""
    if _LOADED_FROM is not None:
        return True
    return bool(load_dotenv())


def env_first(*names: str, default: str = "") -> str:
    """按顺序取第一个非空环境变量（先确保 .env 已加载）。"""
    ensure_env_loaded()
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default