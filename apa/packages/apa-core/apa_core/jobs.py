"""apa-core: 后台任务生命周期管理（H1 · harness-fusion §4.2）。

移植来源：DeepSeek Harness `packages/jobs/jobs/src/types.ts`（MIT）——
owner 围栏 / 幂等取消 / done 恰好一次结算 的语义级 Python 翻译。

首期收编：spy 会话、browser_pick 会话、recorder 会话（此前各自为政的
单例布尔）。与 ServeApp.load_jobs 的边界：load_jobs 是定时流程调度表，
本层是可列举/可取消的后台任务运行时。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

__all__ = ["JobManager", "JobRecord", "JobNotOwned", "JobNotFound"]

TERMINAL = ("done", "cancelled")


@dataclass
class JobRecord:
    id: str
    kind: str
    owner_session: str
    status: str = "running"          # running | done | cancelled
    created_at: float = field(default_factory=time.time)
    settled_at: Optional[float] = None
    result_ref: Optional[str] = None


class JobNotFound(KeyError):
    pass


class JobNotOwned(PermissionError):
    pass


class JobManager:
    """进程内任务注册表。线程安全。

    约束（对应 dsh jobs 协议）：
      - cancel 幂等：对终态任务的重复取消返回原记录，不重复执行回调
      - owner 围栏：非 owner 会话的取消被拒绝（JobNotOwned）
      - 结算恰好一次：settlement 钩子带一次性守卫
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobRecord] = {}
        self._on_cancel: Dict[str, Callable[[], Any]] = {}
        self._on_settle: Dict[str, Callable[[JobRecord], Any]] = {}
        self._settled: set = set()

    # ---- 创建 -----------------------------------------------------------------

    def start(self, kind: str, owner_session: str,
              job_id: Optional[str] = None,
              on_cancel: Optional[Callable[[], Any]] = None,
              on_settle: Optional[Callable[[JobRecord], Any]] = None,
             ) -> JobRecord:
        jid = job_id or f"{kind}_{uuid.uuid4().hex[:10]}"
        with self._lock:
            rec = JobRecord(id=jid, kind=kind, owner_session=owner_session)
            self._jobs[jid] = rec
        self._on_cancel[jid] = on_cancel
        self._on_settle[jid] = on_settle
        return rec

    # ---- 取消（幂等 + 围栏） ---------------------------------------------------

    def cancel(self, job_id: str, actor_session: str) -> JobRecord:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise JobNotFound(job_id)
            if rec.owner_session != actor_session and \
                    actor_session != "__system__":
                raise JobNotOwned(
                    f"job {job_id} 属于 {rec.owner_session}，"
                    f"拒绝 {actor_session} 的取消")
            if rec.status in TERMINAL:
                return rec          # 幂等：终态原样返回
            rec.status = "cancelled"
            rec.settled_at = time.time()
        cb = self._on_cancel.pop(job_id, None)
        if cb is not None:
            try:
                cb()
            except Exception:
                pass  # 取消回调失败不改变已生效的终态
        return rec

    # ---- 完成 -----------------------------------------------------------------

    def complete(self, job_id: str,
                 result_ref: Optional[str] = None) -> JobRecord:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise JobNotFound(job_id)
            if rec.status in TERMINAL:
                return rec
            rec.status = "done"
            rec.result_ref = result_ref
            rec.settled_at = time.time()
            first_settlement = job_id not in self._settled
            self._settled.add(job_id)
        if first_settlement:
            cb = self._on_settle.pop(job_id, None)
            if cb is not None:
                try:
                    cb(rec)
                except Exception:
                    pass
        return rec

    # ---- 查询 -----------------------------------------------------------------

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise JobNotFound(job_id)
            return rec

    def list(self, kind: Optional[str] = None,
             active_only: bool = False) -> List[JobRecord]:
        with self._lock:
            out = list(self._jobs.values())
        if kind:
            out = [j for j in out if j.kind == kind]
        if active_only:
            out = [j for j in out if j.status == "running"]
        return sorted(out, key=lambda j: j.created_at)
