"""apa-core: Serve 常驻服务（设计文档 §13 部署形态的单进程版）。

把控制平面组件拼成一个跑着的系统：
    StudioServer(HTTP 监控/设计器/HITL)
  + Scheduler（cron/event 触发）
  + 本地流程执行（ProcessRunner.trigger 阻塞驱动，journal 落盘 → Studio 可见）

用法：
    app = ServeApp(journals=["data/*.jsonl"],
                   processes_dir="data/processes",
                   registry=load_registries(...))
    app.load_jobs("data/scheduler.yaml")     # cron/event 任务
    port = app.studio_start_background()
    app.dispatch_external_event("e.x.y", {...})   # 外部事件入口
    ...
    app.shutdown()
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .persist import SessionJournal
from .scheduler import Scheduler
from .studio import StudioServer


class ServeError(RuntimeError):
    pass


class ServeApp:
    """单进程常驻：HTTP 面板 + 调度器 + 本地流程执行。"""

    def __init__(
        self,
        journals: List[str],
        *,
        port: int = 8686,
        processes_dir: Optional[str] = None,
        registry=None,
        runs_dir: Optional[str] = None,
        mock_erp: bool = False,
        erp_base_url: str = "",
        token: Optional[str] = None,
        tenant: Optional[str] = None,
        frontend_dist: Optional[str] = None,
        tick_interval_s: float = 1.0,
        session_timeout_s: float = 30.0,
    ) -> None:
        self.registry = registry
        self.runs_dir = Path(runs_dir) if runs_dir else Path("data/runs")
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.tick_interval_s = max(0.2, float(tick_interval_s))
        self.session_timeout_s = float(session_timeout_s)

        # 内置沙盒 ERP（默认开启，让示例流程开箱即跑）
        from .mock_erp import MockERP

        self.mock_erp_inst: Optional[MockERP] = None
        if mock_erp and not erp_base_url:
            self.mock_erp_inst = MockERP()
            erp_port = self.mock_erp_inst.start()
            erp_base_url = f"http://127.0.0.1:{erp_port}"
        self.erp_base_url = erp_base_url.rstrip("/")

        self.studio = StudioServer(
            journals, port=port, token=token, tenant=tenant,
            registry=registry,
            processes_dir=processes_dir,
            frontend_dist=frontend_dist,
            dispatch_event=self._dispatch_external,
            resolve_task=None,
        )
        self.processes_dir = self.studio.processes_dir
        self.scheduler = Scheduler()

        self.http_port: Optional[int] = None
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self.sessions: Dict[str, Dict[str, Any]] = {}

    # ---- 组件挂载 -------------------------------------------------------------
    def register_local_gateway(self, gateway) -> None:
        """注册本地网关会话，使 HITL 网页按钮可解析其人工任务。

        gateway 可为 EmbeddedGateway 或裸 APAGateway。
        """
        g = gateway.gateway if hasattr(gateway, "gateway") else gateway
        sid = g.session_id
        self.sessions[sid] = {"gateway": g}

        def resolver(task_id: str, outcome: str, actor: str) -> bool:
            return g.resolve_human_task(task_id, outcome=outcome, actor=actor)

        self.studio.resolve_task = resolver

    # ---- 任务定义 ---------------------------------------------------------------
    def add_process_job(
        self,
        job_id: str,
        *,
        kind: str,                       # cron | event
        process: str,                    # processes_dir/<stem>.yaml 的文件名 stem
        expr: Optional[str] = None,      # cron 用
        event: Optional[str] = None,     # event 触发名（缺省用流程自带 trigger）
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """注册「到点/到事件即运行流程」的任务。

        处理器在守护线程中执行完整会话（run → journal），不阻塞调度循环。
        """

        def handler(job: Dict[str, Any]) -> None:
            merged = {**(data or {}), **(job.get("data") or {})}
            t = threading.Thread(
                target=self._run_session_job,
                args=(process, event or "", merged),
                daemon=True,
                name=f"apa-job-{job_id}",
            )
            self._threads.append(t)
            t.start()

        if kind == "cron":
            if not expr:
                raise ServeError(f"job {job_id!r}: cron 需要 expr")
            self.scheduler.add_cron(job_id, expr, handler)
        elif kind == "event":
            if not event:
                raise ServeError(f"job {job_id!r}: event 任务需要 event 名")
            self.scheduler.add_event(job_id, event, handler)
        else:
            raise ServeError(f"job {job_id!r}: 未知 kind {kind!r}")

    def load_jobs(self, path: str | Path) -> int:
        """从 scheduler.yaml 批量加载任务。返回任务数。"""
        import yaml as _yaml

        raw = _yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        count = 0
        for entry in raw.get("jobs", []):
            jid = entry.get("id")
            if not jid:
                continue
            self.add_process_job(
                jid,
                kind=entry.get("kind"),
                process=entry.get("process"),
                expr=entry.get("expr"),
                event=entry.get("event"),
                data=entry.get("data") or {},
            )
            count += 1
        return count

    # ---- 会话执行 -----------------------------------------------------------------
    def _build_executors(self, session: str) -> List[Any]:
        """会话级执行器规格：返回裸能力模块列表。

        注意：不要在此处预先注册到自建 router —— 双重包装会让模块的
        peer 绑定停留在内层 router 上，结果回执将被静默丢弃。
        ProcessRunner 注册时会统一把模块 peer/store 重绑到会话身份。
        """
        from apa_executors.api_executor import APIExecutor

        suffix = session[-6:]
        api_mod = APIExecutor(f"bot_{suffix}", session,
                              base_url=self.erp_base_url)
        mods: List[Any] = [(("api", "erp"), api_mod)]

        # M1：macOS 元素识别执行器（非 darwin / 缺框架时静默跳过）
        if sys.platform == "darwin":
            try:
                from apa_executors.ax_executor import AXExecutor

                ax_mod = AXExecutor(f"bot_{suffix}", session)
                mods.append((("desktop.ui", "desktop.click_text"), ax_mod))
            except Exception:  # noqa: BLE001
                pass
            try:
                from apa_executors.ocr_executor import OCRExecutor

                ocr_mod = OCRExecutor(f"bot_{suffix}", session)
                mods.append(("ocr", ocr_mod))
            except Exception:  # noqa: BLE001
                pass
        return mods

    def _run_session_job(
        self,
        process_stem: str,
        trigger_event: str,
        data: Dict[str, Any],
    ) -> None:
        """守护线程体：起一个会话跑到终态，journal 落入 runs_dir。"""
        import time as _t

        from .launcher import ProcessRunner
        from .process import load_process

        session = f"s_serve_{int(_t.time() * 1000) % 100000}"
        process_file = self.processes_dir / f"{process_stem}.yaml"
        proc = load_process(str(process_file))

        journal = SessionJournal(self.runs_dir / f"{session}.jsonl")

        runner = ProcessRunner(
            proc,
            registry=self.registry,
            executors=self._build_executors(session),
            session=session,
            agent_source=f"proc_{session[-6:]}",
            executor_source=f"bot_{session[-6:]}",
            journal=journal,
            tenant_id="serve",
        )
        runner.router.start_observation()
        self.register_local_gateway(runner.gateway)   # HITL 按钮可解析其任务

        # cron 场景无显式事件名 → 回退到流程自身声明的触发事件
        trigger = trigger_event or proc.trigger_name or ""
        result = runner.trigger(trigger, dict(data),
                                timeout_s=self.session_timeout_s)

        journal.record("outcome_summary",
                       session=session, outcome=result["outcome"],
                       steps=len(result["steps"]))

    # ---- 外部事件入口 -----------------------------------------------------------
    def _dispatch_external(self, name: str, data: Dict[str, Any]) -> dict:
        fired = self.scheduler.dispatch_event(name, data)
        return {"dispatched": len(fired)}

    def dispatch_external_event(self, name: str,
                                data: Optional[Dict[str, Any]] = None) -> dict:
        """外部系统投递事件 → 命中的 event 任务依次触发。"""
        return self._dispatch_external(name, data or {})

    # ---- 生命周期 -----------------------------------------------------------------
    def studio_start_background(self) -> int:
        """启动 HTTP 面板与调度循环线程。返回 HTTP 端口。"""
        self._stop.clear()
        self.http_port = self.studio.start_background()
        t = threading.Thread(target=self._tick_loop, daemon=True,
                             name="apa-serve-tick")
        t.start()
        self._threads.append(t)
        return self.http_port

    def _tick_loop(self) -> None:
        while not self._stop.wait(self.tick_interval_s):
            try:
                self.scheduler.tick()
            except Exception as e:  # noqa: BLE001
                print(f"[serve] tick error: {e}")

    def shutdown(self) -> None:
        self._stop.set()
        self.studio.shutdown()
        if self.mock_erp_inst is not None:
            self.mock_erp_inst.stop()