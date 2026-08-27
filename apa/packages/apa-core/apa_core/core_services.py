"""APA 核心服务容器（架构宪法 §二：状态所有权）。

一切可变单例挂此容器，经 create_app 注入；禁止模块级可变全局。
会话型硬件/外部服务（spy/picker/recorder/scrape）为惰性槽位：
「谁启动谁赋值」，容器不预构造。

用法：
    svc = CoreServices(sessions_dir=..., spills_dir=...)
    app = create_app(journals=[...], services=svc)
不传 services 时按 paths.py 默认构建（向后兼容）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, Optional

from .jobs import JobManager
from . import paths as app_paths
from .sessions import SessionStore
from .settings import SettingsManager
from .spill import SpillStore


class NotificationHub:
    """进程内通知总线（H3 二期）：SSE 下行的生产者侧。

    publish 丢弃最旧策略——慢消费者不阻塞引擎；订阅者自带队列。
    """

    def __init__(self, maxsize: int = 512) -> None:
        self._maxsize = maxsize
        self._subs: List["Queue"] = []
        self._lock = __import__("threading").Lock()

    def subscribe(self) -> "Queue":
        q: "Queue" = Queue(maxsize=self._maxsize)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: "Queue") -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, method: str, payload: dict) -> None:
        import time

        evt = {"method": method, "payload": payload,
               "ts": round(time.time(), 3)}
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(evt)
            except Full:
                try:
                    q.get_nowait()   # 丢最旧
                    q.put_nowait(evt)
                except (Empty, Full):
                    pass


@dataclass
class CoreServices:
    """无状态基础设施 + 惰性服务槽。"""

    jobs: JobManager = field(default_factory=JobManager)
    sessions: SessionStore = None          # type: ignore[assignment]
    spills: SpillStore = None              # type: ignore[assignment]
    settings: SettingsManager | None = None  # 惰性：__post_init__ 构建

    # ---- 惰性槽位（API 层赋值；容器不构造） ---------------------------------
    spy: Any = None                        # SpyService | None
    picker: Any = None                     # BrowserPickerService | None
    recorder: Any = None                   # RecorderService | None
    scrape: Any = None                     # ScrapeWizardService | None
    notifications: NotificationHub = field(default_factory=NotificationHub)

    def __post_init__(self) -> None:
        # 防御式收敛：允许传路径字符串，统一转为存储实例
        if isinstance(self.sessions, (str, Path)):
            self.sessions = SessionStore(self.sessions)
        elif self.sessions is None:
            self.sessions = SessionStore(app_paths.sessions_dir())
        if isinstance(self.spills, (str, Path)):
            self.spills = SpillStore(self.spills)
        elif self.spills is None:
            self.spills = SpillStore(app_paths.spills_dir())
        if self.settings is None:
            self.settings = SettingsManager()

    def notify(self, method: str, payload: dict) -> None:
        """Studio notification 发布入口（engine/service 层调用）。"""
        self.notifications.publish(method, payload)

    def require_draft_approved(self, session_id: str,
                               draft_id: str) -> None:
        """H2 计划态确认门：无批准事件即抛 ValueError/PermissionError。"""
        if not draft_id:
            return
        if not session_id:
            raise ValueError("草稿溯源缺失：请携带 session_id 与 draft_id")
        approved = any(
            e.get("kind") == "draft.approved" and
            (e.get("payload") or {}).get("id") == draft_id
            for e in self.sessions.read(session_id))
        if not approved:
            # H3 三期：审批引出同步推送（UI ticker 显示 ⏸ 待审批）
            self.notify("approval.elicit", {
                "session": session_id, "draft_id": draft_id,
                "prompt": f"草稿 {draft_id} 需要批准后才能保存/试运行",
            })
            raise PermissionError(
                f"草稿 {draft_id} 未获批准，未批准的流程不能保存或试运行")

    def rpc_table(self) -> dict:
        """Studio RPC 方法注册表（H3：api 层只做分发与错误映射）。"""
        from dataclasses import asdict

        from .sessions import project_events

        s = self.sessions

        def session_read(p: dict):
            events = s.read(str(p["sid"]))
            return {"id": str(p["sid"]), "events": events,
                    "view": project_events(events)}

        def bgjobs_cancel(p: dict):
            return asdict(self.jobs.cancel(
                str(p["job_id"]),
                actor_session=str(p.get("actor", "__system__"))))

        return {
            "session.list":
                lambda p: {"sessions": s.list_sessions()},
            "session.read": session_read,
            "session.append": lambda p: {"ok": True, "event": s.append(
                str(p["sid"]), str(p["kind"]),
                p.get("payload") or {})},
            "bgjobs.list": lambda p: {"jobs": [
                asdict(j) for j in self.jobs.list(
                    active_only=bool(p.get("active_only")))]},
            "bgjobs.cancel": bgjobs_cancel,
        }


def resolve_services(
        services: Optional[CoreServices],
        *, sessions_dir: Optional[str] = None) -> CoreServices:
    """create_app 兼容入口：显式传入优先，否则按参数/paths 构建。"""
    if services is not None:
        return services
    return CoreServices(
        sessions=SessionStore(sessions_dir or app_paths.sessions_dir()))
