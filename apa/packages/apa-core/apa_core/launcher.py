"""apa-core: 流程启动器 —— 把 ProcessEngine 驱动逻辑从示例中泛化（§10.2）。

任意 process.yaml + 复合执行器规格 → 一次同步运行到终态。
Scheduler 的任务处理器与各示例共用此入口。

    runner = ProcessRunner.from_spec(
        session="s_po_001",
        process="processes/po.yaml",
        modules={("api", "erp"): APIExecutor(...)},
        identities={"executor": "bot_01", "agent": "proc_01"},
    )
    summary = runner.trigger("erp.order.approval_requested", {...})
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .process import ProcessDef, ProcessEngine, load_process
from .registry import load_registries


class LauncherError(RuntimeError):
    pass


class ProcessRunner:
    """单会话流程运行器（嵌入式模式，同步驱动）。"""

    def __init__(
        self,
        proc: ProcessDef,
        *,
        registries_path: Optional[List[Path]] = None,
        registry=None,
        executors: Optional[List[Tuple[tuple, object]]] = None,
        session: str = "s_proc",
        agent_source: str = "proc_01",
        executor_source: str = "bot_01",
        journal=None,
        tenant_id: Optional[str] = None,
    ) -> None:
        from aip import AIPPeer

        from .embedded import EmbeddedGateway
        from .policy import PolicyConfig
        from .rules import RuleBasedAgent  # noqa: F401  (保留扩展点)

        self.proc = proc
        self.session = session

        reg = registry or load_registries(*(registries_path or []))
        self.gateway = EmbeddedGateway(
            session,
            registry=reg,
            policy=PolicyConfig(),
            identities={"executor": executor_source, "agent": agent_source},
            process_id=proc.process_id,
            journal=journal,
            tenant_id=tenant_id,
        )

        # 组装复合执行器：单一协议身份 + 多领域能力模块
        from apa_sdk.composite import CompositeExecutor  # 延迟导入避免环

        router = CompositeExecutor(executor_source, session)
        for prefixes, module in (executors or []):
            router.register(prefixes, module)
        self.router = router

        # 决策侧：ProcessEngine 通过同步 send-and-wait 驱动
        self.agent_peer = AIPPeer(source=agent_source, session_id=session)
        self._pending: Dict[str, Optional[dict]] = {}

        def send_and_wait(name: str, params: dict) -> Tuple[bool, dict]:
            act = self.agent_peer.build_action(name, params=params or None)
            self._pending[act.id] = None
            self.agent_peer.send(act)
            payload = self._pending.pop(act.id)
            if payload is None:
                return False, {"code": "no_result"}
            status = payload.get("status")
            if status == "ok":
                return True, payload.get("data") or {}
            return False, {"code": payload.get("code")}

        self.engine = ProcessEngine(proc, send_and_wait)

        def _complete(outcome: str) -> None:
            # escalated：已挂起等人工，不在此收尾（§4.3）
            if outcome in ("success", "failure"):
                act = self.agent_peer.build_action(
                    "session.complete", params={"outcome": outcome})
                self.agent_peer.send(act)

        self.engine.complete_fn = _complete
        self._inbox_ready = False

        def agent_inbox(raw: dict) -> None:
            cls, msg = self.agent_peer.handle(raw)
            if cls != "accept":
                return
            if msg.type == "event":
                payload = msg.payload
                self.engine.on_trigger(payload.get("name", ""),
                                       payload.get("data") or {})
            elif msg.type == "result" and msg.in_reply_to in self._pending:
                self._pending[msg.in_reply_to] = msg.payload

        self._agent_obj = _AgentShell(agent_inbox, self.agent_peer)
        self.gateway.attach_executor(router, executor_source)
        self.gateway.attach_agent(self._agent_obj, agent_source)
        self.gateway.run()
        router.start_observation()

    # --- 触发 -----------------------------------------------------------------
    def trigger(self, event_name: str, data: dict, *,
                timeout_s: float = 15.0) -> dict:
        """发射触发事件并阻塞至流程终态。返回 {summary, state, outcome}。"""
        self.engine.on_trigger(event_name, data)
        deadline = time.time() + timeout_s
        while time.time() < deadline and not self.engine.run.done:
            self.gateway.tick()
            time.sleep(0.02)
        summary = self.engine.run.summary()
        summary["gateway_state"] = self.gateway.summary()["state"]
        return summary

    @property
    def context_store(self):
        return self.router.context_store


class _AgentShell:
    """最小决策端载体：消息路由交给闭包，peer 由挂载方接线。"""

    def __init__(self, on_message, peer) -> None:
        self.on_message = on_message
        self.peer = peer


def default_registries() -> List[Path]:
    """仓库内置注册表集合（core/browser/desktop/document/api/excel/ocr/dataops）。"""
    apa_root = Path(__file__).resolve().parents[3]
    return [apa_root / "registries" / n for n in
            ("core.yaml", "browser.yaml", "desktop.yaml", "document.yaml",
             "api.yaml", "excel.yaml", "ocr.yaml", "dataops.yaml")]


def run_process(
    process_path: str | Path,
    event_name: str,
    event_data: dict,
    *,
    executors: List[Tuple[tuple, object]],
    session_prefix: str = "s_proc",
    registries: Optional[List[Path]] = None,
    journal_dir: Optional[str | Path] = None,
    seed_contexts: Optional[Dict[str, dict]] = None,
    timeout_s: float = 15.0,
) -> dict:
    """一步式启动：加载 process.yaml → 运行至终态。返回摘要。

    scheduler 的 cron/event 处理器可直接调用本函数。
    """
    proc = load_process(str(process_path))
    journal = None
    if journal_dir is not None:
        journal = SessionJournalSafe(Path(journal_dir),
                                     f"{session_prefix}_{proc.process_id}")
    reg_paths = [str(p) for p in (registries or default_registries())]
    runner = ProcessRunner(
        proc,
        registries_path=reg_paths,
        executors=executors,
        session=f"{session_prefix}_{proc.process_id}",
        journal=journal,
    )
    # CoD 预置：事件只带引用，数据先落入执行器 ContextStore（C5）
    for name, payload in (seed_contexts or []):
        ref = runner.context_store.make_ref(runner.session, name)
        runner.context_store.put(ref, payload)

    result = runner.trigger(event_name, event_data, timeout_s=timeout_s)
    result["context_store"] = runner.context_store
    return result


class SessionJournalSafe:
    """按会话分文件的 JSONL journal（launcher 便捷封装）。"""

    def __init__(self, directory: Path, name: str) -> None:
        from .persist import open_journal
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{name}.jsonl"
        self._journal = open_journal(self.path)

    def record(self, kind: str, **fields) -> dict:
        return self._journal.record(kind, **fields)

    def all(self) -> list:
        return self._journal.all()