"""apa-core: Scheduler 服务（设计文档 §13.1 apa-scheduler）。

控制平面的触发器：
    · Cron 触发 —— 标准五字段表达式，tick(now_ms) 到期即发射
    · Event 触发 —— dispatch_event(name, data) 匹配注册的订阅

同分钟去重：同一 cron 任务在一个自然分钟内只触发一次
（调度器可能被高频 tick 而真实时间未跨分钟）。

处理器签名：handler(job) -> None，job 为触发上下文字典：
    {"job_id", "kind", "spec"/"event", "fired_ms"}
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .cron import CronExpr, CronError


class SchedulerError(ValueError):
    pass


class Scheduler:
    def __init__(self, *, clock=None) -> None:
        self.clock = clock
        self.jobs: Dict[str, dict] = {}
        self._last_fired_minute: Dict[str, str] = {}   # job_id -> "YYYY-MM-DD HH:MM"
        self.fired: List[dict] = []                     # 全部触发记录（审计/测试）

    def _now(self) -> int:
        return self.clock.now_ms() if self.clock else int(time.time() * 1000)

    # --- 注册 -----------------------------------------------------------------
    def add_cron(self, job_id: str, expr: str,
                 handler: Callable[[dict], None]) -> None:
        try:
            cron = CronExpr(expr)
        except CronError as e:
            raise SchedulerError(f"job {job_id!r}: {e}") from e
        self.jobs[job_id] = {
            "job_id": job_id, "kind": "cron",
            "expr": expr, "cron": cron, "handler": handler,
        }

    def add_event(self, job_id: str, event_name: str,
                  handler: Callable[[dict], None], *,
                  data_filter: Optional[Dict[str, object]] = None) -> None:
        if not event_name or "." not in event_name:
            raise SchedulerError(f"job {job_id!r}: bad event name {event_name!r}")
        self.jobs[job_id] = {
            "job_id": job_id, "kind": "event", "event": event_name,
            "data_filter": dict(data_filter or {}), "handler": handler,
        }

    def add_watch(self, job_id: str, path_glob: str,
                  handler: Callable[[dict], None]) -> None:
        """文件监听任务：tick 时对 glob 命中文件做 mtime 快照比对。

        新增或修改的每个文件触发一次 handler({path, mtime_ms})。
        快照存内存 —— 进程重启后首轮视为全量新增（幂等语义由流程侧保证）。
        """
        from pathlib import Path

        if not str(path_glob).strip():
            raise SchedulerError(f"job {job_id!r}: empty watch glob")
        self.jobs[job_id] = {
            "job_id": job_id, "kind": "watch",
            "glob": str(path_glob),
            "snapshot": {},          # abspath -> mtime_ns
            "handler": handler,
            "_Path": Path,
        }

    def _fire_watch(self, job: dict) -> int:
        """扫描 + 比对 + 触发。返回触发次数。"""
        import time as _t

        Path = job["_Path"]
        fired = 0
        snap: dict = job["snapshot"]
        seen_now: dict = {}
        try:
            g = Path(job["glob"])
            matches = list(g.parent.glob(g.name))
        except Exception:
            return 0
        for fp in matches:
            if not fp.is_file():
                continue
            ap = str(fp.resolve())
            try:
                mt = fp.stat().st_mtime_ns
            except OSError:
                continue
            seen_now[ap] = mt
            old = snap.get(ap)
            if old is None or old != mt:
                job["handler"]({"path": ap, "mtime_ms": mt // 1e6})
                fired += 1
        # 已删除文件从快照移除（再次出现视为新增）
        job["snapshot"] = seen_now
        return fired

    def remove(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None

    # --- 触发 -----------------------------------------------------------------
    def tick(self, now_ms: Optional[int] = None) -> List[dict]:
        """推进 cron 任务。返回本次触发的 job 上下文列表。"""
        now = now_ms if now_ms is not None else self._now()
        fired: List[dict] = []
        for job in list(self.jobs.values()):
            if job.get("kind") == "watch":
                n = self._fire_watch(job)
                if n:
                    ctx = {"job_id": job["job_id"], "kind": "watch",
                           "ts_ms": now_ms or self._now(), "count": n}
                    fired.append(ctx)
                    self.fired.append(ctx)
                continue
            if job["kind"] != "cron":
                continue
            dt = datetime.fromtimestamp(now / 1000)
            minute_key = dt.strftime("%Y-%m-%d %H:%M")
            if not job["cron"].matches(dt):
                continue
            if self._last_fired_minute.get(job["job_id"]) == minute_key:
                continue  # 同一分钟只发一次
            self._last_fired_minute[job["job_id"]] = minute_key
            ctx = {"job_id": job["job_id"], "kind": "cron",
                   "spec": job["expr"], "fired_ms": now}
            fired.append(ctx)
            self.fired.append(ctx)
            job["handler"](ctx)
        return fired

    def dispatch_event(self, event_name: str, data: Optional[dict] = None) -> List[dict]:
        """事件到达 → 命中的 event 订阅依次触发。返回触发的上下文列表。"""
        data = data or {}
        fired: List[dict] = []
        for job in list(self.jobs.values()):
            if job.get("kind") == "watch":
                n = self._fire_watch(job)
                if n:
                    ctx = {"job_id": job["job_id"], "kind": "watch",
                           "ts_ms": now_ms or self._now(), "count": n}
                    fired.append(ctx)
                    self.fired.append(ctx)
                continue
            if job["kind"] != "event" or job["event"] != event_name:
                continue
            ok = all(data.get(k) == v
                     for k, v in (job.get("data_filter") or {}).items())
            if not ok:
                continue
            ctx = {"job_id": job["job_id"], "kind": "event",
                   "event": event_name, "data": dict(data),
                   "fired_ms": self._now()}
            fired.append(ctx)
            self.fired.append(ctx)
            job["handler"](ctx)
        return fired

    def summary(self) -> dict:
        by_kind: Dict[str, int] = {}
        for j in self.jobs.values():
            by_kind[j["kind"]] = by_kind.get(j["kind"], 0) + 1
        return {"jobs": len(self.jobs), "by_kind": by_kind,
                "fired_total": len(self.fired)}