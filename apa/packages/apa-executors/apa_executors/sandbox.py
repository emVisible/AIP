"""apa-executors: macOS Seatbelt 沙箱封装（H4 · harness-fusion 资产 #6）。

移植来源：OpenAI Codex `codex-rs/sandboxing/src/seatbelt.rs`（Apache-2.0）
的命令装配模式；策略模板见 profiles/code_python_default.sbpl
（数据文件直接取自 Codex 策略裁剪，NOTICE 同目录）。

形态：
  build_command(argv, workspace) → ["/usr/bin/sandbox-exec", "-f", <渲染后
  profile>, ...argv]
  - 非 darwin / sandbox-exec 缺失时 is_available()=False，调用方回退直跑
  - 渲染后的 profile 缓存于 data/sandbox/（按 workspace+tmpdir 哈希）

边界：读放开、写限工作区与系统临时目录、网络默认拒绝。
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

__all__ = ["is_available", "build_command", "SEATBELT_PATH"]

SEATBELT_PATH = "/usr/bin/sandbox-exec"

_TEMPLATE = (Path(__file__).parent / "profiles" /
             "code_python_default.sbpl").read_text(encoding="utf-8")


def is_available() -> bool:
    """darwin 且存在 /usr/bin/sandbox-exec。"""
    import sys

    if sys.platform != "darwin":
        return False
    return Path(SEATBELT_PATH).exists()


def _render_profile(workspace: Path, cwd: Path) -> str:
    tmpdir = tempfile.gettempdir()
    text = _TEMPLATE.replace("{workspace}", str(workspace))
    text = text.replace("{cwd}", str(cwd))
    text = text.replace("{tmpdir}", tmpdir)
    return text


def _profile_file(workspace: Path, cwd: Path) -> Path:
    """渲染并缓存 profile（内容寻址，同参复用）。"""
    text = _render_profile(workspace, cwd)
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    out = Path("data") / "sandbox" / f"code_python_{h}.sbpl"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return out


def build_command(argv: list[str], workspace: Path | None = None,
                  cwd: Path | None = None) -> list[str]:
    """把普通命令包装为沙箱命令。非 darwin 抛 RuntimeError——
    调用方必须先用 is_available() 判定。"""
    if not is_available():
        raise RuntimeError(
            "seatbelt unavailable (darwin + /usr/bin/sandbox-exec required)")
    ws = (workspace or Path.cwd()).resolve()
    c = (cwd or Path.cwd()).resolve()
    profile = _profile_file(ws, c)
    return [SEATBELT_PATH, "-f", str(profile), *argv]
