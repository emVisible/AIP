"""apa-core: spill 大结果落盘中间件（H1 · harness-fusion §4.3）。

移植来源：DeepSeek Harness `packages/spill/spill/src/{index,types}.ts`（MIT）
引用契约的语义级翻译。

行为：白名单动作的结果序列化超过阈值时，原文写入
`<dir>/<spill_ref>.json`，上下文中只保留引用对象：
    {"__spill__": true, "spill_ref": str, "bytes": int,
     "preview": str(≤2KB), "truncated": True}
消费方凭 spill_ref 经 ``read_spill`` 回读原文。

设计偏差记录（相对融合文档 §4.3 初稿）：引擎出口的全量接管会破坏
``{{steps.<id>.rows}}`` 的模板消费语义（foreach 需要真实数组），
故本期限定接入点为试运行响应层与显式调用方；引擎出口待引入
spill 回读动作（H2 一并设计）后全量启用。
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

from .paths import spills_dir
from typing import Any, Dict, Tuple

__all__ = ["maybe_spill", "read_spill", "SpillCorrupt"]

SPILL_THRESHOLD_BYTES = 32_000
PREVIEW_BYTES = 2_000

# 首期白名单（harness-fusion §4.3）
WHITELIST = {
    "browser.extract_table",
    "file.read_csv",
    "doc.extract_text",
    "ocr.extract",
}


class SpillCorrupt(RuntimeError):
    """spill 文件缺失或损坏（拒绝静默空值）。"""


class SpillStore:
    """进程内单例由调用方持有；线程安全。"""

    def __init__(self, directory: Path | str,
                 threshold: int = SPILL_THRESHOLD_BYTES) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._threshold = threshold
        self._lock = threading.Lock()

    # ---- 写 -------------------------------------------------------------------

    def maybe_spill(self, action_name: str,
                    result: Any) -> Tuple[Any, bool]:
        """超阈值白名单结果 → 引用对象；其余原样返回。"""
        if action_name not in WHITELIST:
            return result, False
        try:
            blob = json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            return result, False
        if len(blob.encode("utf-8")) < self._threshold:
            return result, False
        ref = f"{action_name.replace('.', '_')}_" \
              f"{int(time.time() * 1000):x}_" \
              f"{hashlib.sha1(blob.encode()).hexdigest()[:8]}"
        path = self._dir / f"{ref}.json"
        with self._lock:
            path.write_text(blob, encoding="utf-8")
        preview = blob[:PREVIEW_BYTES]
        ref_obj = {
            "__spill__": True,
            "spill_ref": ref,
            "bytes": len(blob.encode("utf-8")),
            "preview": preview,
            "truncated": True,
        }
        return ref_obj, True

    # ---- 读 -------------------------------------------------------------------

    def read_spill(self, spill_ref: str) -> Any:
        """按引用回读原文。缺失/损坏抛 SpillCorrupt（拒绝静默空值）。"""
        if "/" in spill_ref or ".." in spill_ref or not spill_ref:
            raise SpillCorrupt(f"illegal spill ref: {spill_ref!r}")
        path = self._dir / f"{spill_ref}.json"
        if not path.exists():
            raise SpillCorrupt(f"spill 不存在: {spill_ref}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise SpillCorrupt(f"spill 损坏: {spill_ref}: {e}") from e


_default_store = SpillStore(spills_dir())


def default_store() -> SpillStore:
    """引擎内置动作（context.spill_read）使用的默认存储。"""
    return _default_store


def set_default_store(store: SpillStore) -> None:
    """测试/装配覆盖入口（架构宪法 §二：唯一允许的全局替换点）。"""
    global _default_store
    _default_store = store


def maybe_spill(action_name: str, result: Any) -> Tuple[Any, bool]:
    """模块级便捷入口（默认目录 data/spills）。供试运行层使用。"""
    return _default_store.maybe_spill(action_name, result)


def spill_test_response(result: Dict[str, Any]) -> int:
    """试运行响应层 spill（H3 自 api.py 下沉）：白名单大结果落盘，
    steps[].result 替换为引用对象。返回 spill 数量。"""
    count = 0
    for st in result.get("steps", []) or []:
        if st.get("status") == "ok" and "result" in st:
            ref_obj, did = maybe_spill(str(st.get("action")),
                                       st["result"])
            if did:
                st["result"] = ref_obj
                st["spilled"] = True
                count += 1
    if count:
        result["spilled_results"] = count
    return count
