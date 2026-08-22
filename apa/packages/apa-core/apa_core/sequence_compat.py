"""apa-core: AIP Receiver 的恢复扩展（不动上游 SDK）。

RecoverableReceiver 增加 apply_seq：持久化恢复时直接重建游标基线，
使 duplicate/stale 判定与 hello(cursors) 在重启后保持正确。

GapTolerantReceiver：嵌入式模式专用（§13.2 模式 C）。
Gateway 拦截型动作（session.complete / human.task.create —— 网关自处理
不转发 Executor）会消耗 agent 流的 seq 却不出现在执行器入站流上，
形成永久性序号空洞。嵌入式对端以「最后可见消息」为基线即可；
网关侧仍严格（S1–S5）。独立 WS 部署不走此容忍——由 SPEC §7.4 的
resume/cursors 协议处理。
"""
from __future__ import annotations

from aip import Receiver


class RecoverableReceiver(Receiver):
    tolerate_gaps = False

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


class GapTolerantReceiver(Receiver):
    """gap → accept：拦截型动作造成的空洞直接越过并推进游标。

    仅由 EmbeddedGateway 注入到对端 peer；协议内核与网关不受影响。
    """

    def classify(self, msg) -> str:
        kind = super().classify(msg)
        if kind == "gap":
            return "accept"  # apply() 会把游标推进到本条 seq
        return kind