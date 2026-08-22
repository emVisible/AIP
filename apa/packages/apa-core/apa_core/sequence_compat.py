"""apa-core: AIP Receiver 的恢复扩展（不动上游 SDK）。

RecoverableReceiver 增加 apply_seq：持久化恢复时直接重建游标基线，
使 duplicate/stale 判定与 hello(cursors) 在重启后保持正确。
"""
from __future__ import annotations

from aip import Receiver


class RecoverableReceiver(Receiver):
    def apply_seq(self, session: str, source: str, seq: int) -> None:
        """恢复用：把 (session, source) 游标推进到 seq（只前进不后退）。"""
        key = (session, source)
        cur = self._applied_seq.get(key, 0)
        if seq <= cur:
            return
        self._applied_seq[key] = seq
        self._applied_count[key] = self._applied_count.get(key, 0) + (seq - cur)
        ids = self._ids.setdefault(key, set())
        for s in range(cur + 1, seq + 1):
            ids.add(f"recovered#{s}")
        self.history.append((session, source, seq))