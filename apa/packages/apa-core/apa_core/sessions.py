"""apa-core: 会话事件溯源（H1 · harness-fusion §4.1）。

移植来源：
  - DeepSeek Harness `packages/core/session`（MIT）：「模型可见 ⟺ 已记录」
    不变量与 durable 事件二分
  - OpenAI Codex `codex-rs/rollout`（Apache-2.0）：append-only JSONL 形态

设计：
  一 session 一文件 `<dir>/<session_id>.jsonl`；
  事件 envelope `{"seq": i, "ts": float, "kind": str, "payload": dict}`，
  seq 从 1 单调递增。append 前读尾取 seq；read 时全量校验连续性——
  中间断裂/重复视为篡改抛 :class:`SessionTampered`，仅末行撕裂（崩溃残页）
  容忍截断。

  投影 ``project_events`` 是纯函数：events → 对话视图（Workbench 消息 +
  草稿卡片状态），幂等可重放。

与 process journal 的边界：journal 是流程运行审计流，本层是对话会话流，
二者并存互不替代（见 docs/harness-fusion.md §4.1）。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

__all__ = ["SessionStore", "SessionTampered", "project_events"]


class SessionTampered(RuntimeError):
    """会话日志完整性破坏（seq 断裂/重复/中间坏行）。"""


class SessionStore:
    """对话会话事件存储。进程内单例由 API 层持有；线程安全。"""

    def __init__(self, directory: Path | str) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ---- 路径 -----------------------------------------------------------------

    def _path(self, session_id: str) -> Path:
        if not session_id or "/" in session_id or ".." in session_id:
            raise ValueError(f"illegal session id: {session_id!r}")
        return self._dir / f"{session_id}.jsonl"

    # ---- 写 -------------------------------------------------------------------

    def append(self, session_id: str, kind: str,
               payload: Dict[str, Any]) -> Dict[str, Any]:
        """追加事件；seq 自动递增。返回完整事件。"""
        path = self._path(session_id)
        with self._lock:
            last_seq = self._last_seq(path)
            event = {
                "seq": last_seq + 1,
                "ts": round(time.time(), 3),
                "kind": kind,
                "payload": payload,
            }
            line = json.dumps(event, ensure_ascii=False)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return event

    def _last_seq(self, path: Path) -> int:
        if not path.exists():
            return 0
        events, torn = _parse_jsonl(path)
        del torn  # 撕裂尾行不影响追加（新事件从 max(seq)+1 起）
        return events[-1]["seq"] if events else 0

    # ---- 读 -------------------------------------------------------------------

    def read(self, session_id: str) -> List[Dict[str, Any]]:
        """全量读取并校验完整性。中间损坏抛 SessionTampered；
        末行撕裂（崩溃残页）容忍截断。"""
        path = self._path(session_id)
        with self._lock:
            if not path.exists():
                return []
            try:
                events, _torn = _parse_jsonl(path)
            except ValueError as e:
                raise SessionTampered(f"{session_id}: 中间存在损坏行: {e}")
        prev = 0
        for e in events:
            if e["seq"] != prev + 1:
                raise SessionTampered(
                    f"{session_id}: seq 断裂 期望 {prev + 1} 实得 "
                    f"{e.get('seq')}")
            prev = e["seq"]
        return events

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).exists()

    def list_sessions(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for p in sorted(self._dir.glob("*.jsonl")):
            st = p.stat()
            sid = p.stem
            n = 0
            try:
                with p.open(encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            n += 1
            except OSError:
                continue
            out.append({"id": sid, "events": n,
                        "mtime": st.st_mtime, "bytes": st.st_size})
        return out


# ---- 解析（模块级，便于测试注入撕裂场景） -------------------------------------

def _parse_jsonl(path: Path) -> tuple[List[Dict[str, Any]], bool]:
    """解析 JSONL。返回 (events, has_torn_tail)。中间坏行直接抛 ValueError，
    由调用方转 SessionTampered；末行不完整（无换行/JSON 截断）容忍为 torn。"""
    events: List[Dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    if not text:
        return events, False
    lines = text.split("\n")
    torn_tail = False
    if lines[-1] == "":
        lines.pop()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            is_last_content = (i == len(lines) - 1)
            if is_last_content and not text.endswith("\n"):
                torn_tail = True   # 崩溃残页：容忍并忽略
                break
            raise
    return events, torn_tail


# ---- 投影（纯函数） ------------------------------------------------------------

def project_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """events → 对话视图。幂等：同一输入多次调用输出一致。

    视图条目：
      {"type":"message","role":"user"|"apa","text":str}
      {"type":"draft","id":str,"yaml":str,"template":str,
       "state":"pending"|"approved"|"discarded"}
    后续 kind 在此单点扩展（H3 与 Studio 协议对齐时迁移）。
    """
    views: List[Dict[str, Any]] = []
    drafts: Dict[str, Dict[str, Any]] = {}
    for e in events:
        kind = e.get("kind", "")
        payload = e.get("payload") or {}
        if kind == "message.user":
            views.append({"type": "message", "role": "user",
                          "text": str(payload.get("text", ""))})
        elif kind == "message.assistant":
            views.append({"type": "message", "role": "apa",
                          "text": str(payload.get("text", ""))})
        elif kind == "draft.created":
            d = {"type": "draft",
                 "id": str(payload.get("id", "")),
                 "yaml": str(payload.get("yaml", "")),
                 "template": str(payload.get("template", "")),
                 "state": "pending"}
            drafts[d["id"]] = d
            views.append(d)
        elif kind == "draft.approved" or kind == "draft.discarded":
            d = drafts.get(str(payload.get("id", "")))
            if d is not None:
                d["state"] = ("approved" if kind == "draft.approved"
                              else "discarded")
        # 未知 kind 静默跳过（向前兼容：旧投影读新日志不炸）
    return views
