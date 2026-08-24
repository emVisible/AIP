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

import os
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




def make_llm_decision_fn(client, *, session: str = "",
                         max_decisions: int = 20):
    """把 LLMClient 适配为 ProcessEngine.decision_fn 契约。

    - 引擎契约：(ctx_list, available_actions) -> {"outcome": str, **_meta}
    - 预算：每会话 max_decisions 次，超出折叠为 uncertain(budget_exhausted)
    - 异常/超时：LLMClient 内部已降级 uncertain；此处再兜底一层
    """
    import time as _t

    counter = {"n": 0}

    def decide(ctx_list, available_actions):
        if counter["n"] >= max_decisions:
            return {"outcome": "uncertain",
                    "_reason": "budget_exhausted",
                    "_level": "L2",
                    "_budget_used": counter["n"]}
        counter["n"] += 1
        t0 = _t.perf_counter()
        try:
            raw = client.decide(
                event_name="ai_decision",
                event_data={"context": ctx_list},
                allowed_actions=list(available_actions),
            )
        except Exception as e:  # noqa: BLE001
            raw = {"uncertain": f"llm_error:{type(e).__name__}"}
        ms = round((_t.perf_counter() - t0) * 1000, 1)
        if "action" in raw:
            return {"outcome": str(raw["action"]),
                    "params": raw.get("params") or {},
                    **({"target": raw["target"]}
                       if raw.get("target") else {}),
                    "_level": "L2", "_ms": ms,
                    "_budget_used": counter["n"]}
        reason = raw.get("uncertain", "?")
        return {"outcome": "uncertain", "_reason": str(reason)[:120],
                "_level": "L2", "_ms": ms,
                "_budget_used": counter["n"]}

    decide.session = session
    return decide

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
        ws_port: Optional[int] = None,
        ws_agent_sources: Optional[List[str]] = None,
        llm_client=None,
    ) -> None:
        """ws_port 非 None 时启动内嵌 WS 网关（外部决策引擎接入点）。

        ws_agent_sources：允许以 agent 角色接入的额外身份白名单
        （默认含 "dsh_agent_001"，与 run-agent.mjs 缺省 source 对齐）。
        """
        self.registry = registry
        self.runs_dir = Path(runs_dir) if runs_dir else Path("data/runs")
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.tick_interval_s = max(0.2, float(tick_interval_s))
        self.session_timeout_s = float(session_timeout_s)
        self.ws_port_requested = ws_port
        self.ws_agent_sources = list(ws_agent_sources or ["dsh_agent_001"])
        self.ws_server = None            # WsGatewayServer（WS 线程内）
        self._ws_thread: Optional[threading.Thread] = None

        # M1：内置 LLM 决策（env 有 Key 才启用；可注入 Fake 用于测试）
        from .config import env_first

        def _usable_key() -> bool:
            v = env_first("APA_LLM_API_KEY", "DEEPSEEK_API_KEY")
            # 占位/注释值（模板 .env 的 "# 必填…"）不视为已配置
            return bool(v) and not v.strip().startswith("#")

        self.llm_client = llm_client
        if self.llm_client is None:
            if _usable_key():
                from .llm import LLMClient

                self.llm_client = LLMClient(timeout_s=20.0)
        self.llm_max_decisions = int(
            os.environ.get("APA_LLM_MAX_DECISIONS", "20"))

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
        self._job_specs: Dict[str, Dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()
        self.jobs_path: Optional[Path] = None

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

        if kind == "watch":
            if not expr:
                raise ServeError(
                    f"job {job_id!r}: watch 需要 expr（监听路径 glob）")

            def watch_handler(evt: Dict[str, Any]) -> None:
                merged = {**(data or {}), **evt}
                t2 = threading.Thread(
                    target=self._run_session_job,
                    args=(process, f"file.changed", merged),
                    daemon=True, name=f"apa-job-{job_id}-watch",
                )
                self._threads.append(t2)
                t2.start()

            self.scheduler.add_watch(job_id, expr, watch_handler)
        elif kind == "cron":
            if not expr:
                raise ServeError(f"job {job_id!r}: cron 需要 expr")
            self.scheduler.add_cron(job_id, expr, handler)
        elif kind == "event":
            if not event:
                raise ServeError(f"job {job_id!r}: event 任务需要 event 名")
            self.scheduler.add_event(job_id, event, handler)
        else:
            raise ServeError(f"job {job_id!r}: 未知 kind {kind!r}")

        # 规格（可持久化、可 CRUD）——handler 不可序列化故单列
        self._job_specs[job_id] = {
            "id": job_id, "kind": kind, "process": process,
            "expr": expr, "event": event, "data": dict(data or {}),
        }

    def load_jobs(self, path: str | Path) -> int:
        """从 scheduler.yaml 批量加载任务。返回任务数；记录持久化路径。"""
        import yaml as _yaml

        self.jobs_path = Path(path)
        raw = _yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        count = 0
        for entry in raw.get("jobs", []):
            jid = entry.get("id")
            if not jid:
                continue
            with self._jobs_lock:
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

    # ---- M2 任务 CRUD ---------------------------------------------------------
    def list_job_specs(self) -> Dict[str, Any]:
        """任务规格列表 + cron 下次触发时间。"""
        from .cron import next_after, CronError

        items = []
        for jid, sp in sorted(self._job_specs.items()):
            item = dict(sp)
            item["exists"] = (self.processes_dir /
                              f"{sp['process']}.yaml").is_file()
            if sp["kind"] == "cron":
                try:
                    item["next_run"] = next_after(
                        sp["expr"]).isoformat(timespec="minutes")
                except Exception as e:  # noqa: BLE001
                    item["next_run"] = None
                    item["next_error"] = str(e)[:80]
            items.append(item)
        return {"jobs": items, "count": len(items)}

    def upsert_job_spec(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """创建/更新任务：校验 → 热替换调度器条目 → 持久化。"""
        jid = str(spec.get("id") or "").strip()
        kind = spec.get("kind")
        process = str(spec.get("process") or "").strip()
        if not jid:
            raise ServeError("job id required")
        if kind not in ("cron", "event", "watch"):
            raise ServeError(f"kind must be cron|event|watch, got {kind!r}")
        if not process:
            raise ServeError("process required")

        with self._jobs_lock:
            # 先在调度器层热替换（失败则不留半状态）
            if jid in self.scheduler.jobs:
                self.scheduler.remove(jid)
            try:
                self.add_process_job(
                    jid, kind=kind, process=process,
                    expr=spec.get("expr"),
                    event=spec.get("event"),
                    data=spec.get("data") or {})
            except Exception:
                if jid in self._job_specs and                         jid not in self.scheduler.jobs:
                    pass  # 新建失败的规格也不保留
                raise
            self._job_specs[jid] = {
                "id": jid, "kind": kind, "process": process,
                "expr": spec.get("expr"), "event": spec.get("event"),
                "data": dict(spec.get("data") or {}),
            }
            self._persist_jobs_locked()
        return {"saved": jid}

    def remove_job_spec(self, jid: str) -> Dict[str, Any]:
        with self._jobs_lock:
            existed_sched = self.scheduler.remove(jid)
            existed_spec = self._job_specs.pop(jid, None) is not None
            if existed_spec or existed_sched:
                self._persist_jobs_locked()
        return {"removed": jid,
                "existed": existed_spec or existed_sched}

    def run_job_now(self, jid: str) -> Dict[str, Any]:
        """手动立即触发一次（等价于其事件/到点路径）。"""
        with self._jobs_lock:
            sp = self._job_specs.get(jid)
        if sp is None:
            raise ServeError(f"unknown job {jid!r}")

        merged = dict(sp.get("data") or {})
        trigger_event = (sp.get("event") or "") if sp["kind"] == "event" \
            else ("file.changed" if sp["kind"] == "watch"
                  else f"manual.{jid}")
        t = threading.Thread(
            target=self._run_session_job,
            args=(sp["process"], trigger_event, merged),
            daemon=True, name=f"apa-job-{jid}-manual",
        )
        self._threads.append(t)
        t.start()
        return {"triggered": jid}

    def _persist_jobs_locked(self) -> None:
        """原子写 scheduler.yaml（调用方须已持有 _jobs_lock）。"""
        import os
        import tempfile
        import yaml as _yaml

        if self.jobs_path is None:
            return  # 无持久化路径（纯编程式使用）→ 跳过
        doc = {"jobs": [
            {k: v for k, v in sp.items() if k != "exists"}
            for _, sp in sorted(self._job_specs.items())
        ]}
        payload = _yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
        d = os.path.dirname(self.jobs_path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".yaml", dir=d)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, self.jobs_path)

    # ---- 会话执行 -----------------------------------------------------------------
    def _build_executors(self, session: str) -> List[Any]:
        """会话级执行器规格：返回裸能力模块列表。

        注意：不要在此处预先注册到自建 router —— 双重包装会让模块的
        peer 绑定停留在内层 router 上，结果回执将被静默丢弃。
        ProcessRunner 注册时会统一把模块 peer/store 重绑到会话身份。
        """
        from apa_executors.api_executor import APIExecutor
        from apa_executors.data_executor import DataExecutor

        suffix = session[-6:]
        api_mod = APIExecutor(f"bot_{suffix}", session,
                              base_url=self.erp_base_url)
        mods: List[Any] = [(("api", "erp"), api_mod)]

        # 数据工具包（string/file/data/encode/json/dt/hash 全域路由）
        data_mod = DataExecutor(f"bot_{suffix}", session)
        mods.append(("data", data_mod))

        # M-A3: llm.text 文本任务（无 Key 时 dependency_missing 优雅降级）
        try:
            from apa_core.llm_actions import LlmTextExecutor

            mods.append(("llm", LlmTextExecutor(f"bot_{suffix}", session)))
        except Exception:  # noqa: BLE001
            pass

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

        decision_fn = None
        if self.llm_client is not None:
            decision_fn = make_llm_decision_fn(
                self.llm_client, session=session,
                max_decisions=self.llm_max_decisions)

        runner = ProcessRunner(
            proc,
            registry=self.registry,
            executors=self._build_executors(session),
            session=session,
            agent_source=f"proc_{session[-6:]}",
            executor_source=f"bot_{session[-6:]}",
            journal=journal,
            tenant_id="serve",
            decision_fn=decision_fn,
        )
        runner.router.start_observation()
        self.register_local_gateway(runner.gateway)   # HITL 按钮可解析其任务

        # R3：接入内嵌 WS 网关池 → 外部决策引擎（dsh）可加入该会话
        if self.ws_server is not None:
            core_gw = getattr(runner.gateway, "gateway", runner.gateway)
            self.extend_agent_identities(core_gw, self.ws_agent_sources)
            self.ws_server.register_session(session, core_gw)

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
        if self.ws_port_requested is not None:
            self.start_ws_gateway(self.ws_port_requested)
        return self.http_port

    # ---- 内嵌 WS 网关（外部决策引擎接入点，R3）---------------------------------
    def start_ws_gateway(self, port: int) -> int:
        """独立线程 + asyncio loop 启动 WsGatewayServer。返回实际端口。"""
        import asyncio

        from .ws_gateway import WsGatewayServer

        self.ws_server = WsGatewayServer(port=port)

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._ws_loop = loop
            loop.run_until_complete(self.ws_server.start())
            print(f"[serve] ws gateway ready on :{self.ws_server.port}")
            try:
                loop.run_until_complete(self.ws_server.serve_forever())
            finally:
                loop.close()

        t = threading.Thread(target=_run, daemon=True,
                             name="apa-serve-ws")
        self._ws_thread = t
        t.start()
        # 等待端口就绪（start() 在事件循环里完成）
        import time as _t
        deadline = _t.time() + 5
        while _t.time() < deadline:
            if getattr(self.ws_server, "_server", None) is not None:
                break
            _t.sleep(0.05)
        return self.ws_server.port

    @staticmethod
    def extend_agent_identities(gateway, extra_sources: List[str]) -> None:
        """把外部决策引擎身份并入 gateway agent 白名单（I9）。"""
        current = gateway.identities.get("agent")
        merged: List[str] = []
        for src in ([current] if isinstance(current, str)
                    else list(current or [])):
            if src not in merged:
                merged.append(src)
        for src in extra_sources:
            if src not in merged:
                merged.append(src)
        gateway.identities["agent"] = merged

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