"""Phase 6 补漏回归：拦截型动作的序号空洞修复（GapTolerantReceiver）+
Studio 网页人工审批交互端到端。"""
import asyncio
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from aip import AIPPeer, Receiver, make_action, make_event

from apa_core.embedded import EmbeddedGateway
from apa_core.mock_erp import MockERP
from apa_core.persist import SessionJournal
from apa_core.policy import PolicyConfig
from apa_core.registry import load_registries
from apa_core.rules import RuleBasedAgent, RuleEngine
from apa_core.sequence_compat import GapTolerantReceiver
from apa_core.studio import StudioServer

APA_ROOT = Path(__file__).resolve().parent.parent
SESSION = "s_p6b_001"
EXEC, AGENT = "bot_01", "rule_01"


def registries():
    return load_registries(
        APA_ROOT / "registries" / "core.yaml",
        APA_ROOT / "registries" / "document.yaml",
        APA_ROOT / "registries" / "api.yaml")


class TestGapTolerantReceiver:
    def _receiver_with_history(self):
        global m2
        r = GapTolerantReceiver()
        m1 = make_action(SESSION, AGENT, "a.one")
        m1.seq = 1
        assert r.classify(m1) == "accept"
        r.apply(m1)
        globals()["m2"] = make_action(SESSION, AGENT, "a.two")
        globals()["m2"].seq = 2  # seq2 视为已被拦截动作消耗（未 apply）
        return r

    def test_gap_is_upgraded_to_accept(self):
        r = self._receiver_with_history()
        m3 = make_action(SESSION, AGENT, "a.three")  # seq2 被拦截动作消耗
        m3.seq = 3
        assert Receiver().classify(m3) == "gap"      # 内核语义不变
        assert r.classify(m3) == "accept"            # 嵌入式容忍
        r.apply(m3)
        # 游标已推进：后续连续消息正常接受，旧消息仍 stale
        m4 = make_action(SESSION, AGENT, "a.four")
        m4.seq = 4
        assert r.classify(m4) == "accept"
        # 同 id 重放 → duplicate；不同 id 的旧序号 → stale
        replay = make_action(SESSION, AGENT, "a.three", id=m3.id)
        replay.seq = 3
        assert r.classify(replay) == "duplicate"
        other_old = make_action(SESSION, AGENT, "a.two", id=m2.id)
        other_old.seq = 2
        assert r.classify(other_old) == "stale"

    def test_stale_and_duplicate_semantics_preserved(self):
        r = GapTolerantReceiver()
        m1 = make_action(SESSION, AGENT, "a.one")
        m1.seq = 1
        r.apply(m1)
        assert r.classify(m1) == "duplicate"         # 同 id 重放
        older = make_action(SESSION, AGENT, "a.zero")
        older.seq = 0
        assert r.classify(older) == "stale"


class TestInterceptionGapRegression:
    """回归：human.task.create 拦截后再发同源动作，执行器必须收到。

    修复前：拦截动作消耗 agent 流 seq 但不转发执行器 → 执行器视角
    出现永久空洞（期望 seq2 收到 seq3）→ 后续动作全部静默丢弃。
    """

    def test_action_after_interception_reaches_executor(self):
        erp = MockERP()
        port = erp.start()
        gw = EmbeddedGateway(
            SESSION, registry=registries(),
            identities={"executor": EXEC, "agent": AGENT},
            journal=SessionJournal(Path(__file__).with_name("_p6b.jsonl")),
        )
        g = gw.gateway
        from apa_executors.api_executor import APIExecutor
        from apa_sdk.composite import CompositeExecutor

        router = CompositeExecutor(EXEC, SESSION)
        api_mod = APIExecutor(EXEC, SESSION,
                              base_url=f"http://127.0.0.1:{port}")
        router.register(("api", "erp"), api_mod)
        agent = RuleBasedAgent(AIPPeer(source=AGENT, session_id=SESSION), [])
        gw.attach_executor(router, EXEC)
        gw.attach_agent(agent, AGENT)
        gw.run()

        executed = []
        orig = api_mod._execute_action
        api_mod._execute_action = \
            lambda n, p: (executed.append(n), orig(n, p))[1]

        # seq1: 正常转发；seq2: human.task.create 被 Gateway 拦截；
        # seq3: 修复前会因空洞被丢弃 —— 必须到达执行器
        for seq, (name, params) in enumerate([
            ("api.http.post", {"url": f"http://127.0.0.1:{port}/notify",
                               "json": {"step": 1}}),
            ("human.task.create", {"task_type": "approval",
                                   "assignee_role": "ops",
                                   "context_ref": f"ctx_{SESSION}_x"}),
            ("erp.invoice.create", {"invoice_no": "I-9", "total": 1.0}),
        ], start=1):
            m = make_action(SESSION, AGENT, name, params=params)
            m.seq = seq
            g.deliver("agent", m.to_dict())   # 完整投递（receive 只返回不路由）
            if name == "human.task.create":
                task_id = g.human.open_tasks()[-1]["task_id"]
                assert g.resolve_human_task(task_id, outcome="approve")

        time_sleep = 0.05
        import time as _t
        _t.sleep(time_sleep * 2)

        assert "api.http.post" in executed
        assert "erp.invoice.create" in executed   # 修复点：不再被空洞吞掉
        assert len(erp.invoices) == 1
        assert g.sm.state == "RUNNING"            # resolve 后恢复
        erp.stop()


class TestStudioInteractiveApproval:
    def test_buttons_render_and_resolve_endpoint(self, tmp_path):
        """网页按钮（渲染）+ POST 解析（与浏览器 fetch 行为一致）全链路。"""
        jpath = tmp_path / "hitl.jsonl"
        gw = EmbeddedGateway(SESSION, registry=registries(),
                             identities={"executor": EXEC, "agent": AGENT},
                             journal=SessionJournal(jpath))
        g = gw.gateway
        studio = StudioServer([str(jpath)], port=0,
                              resolve_task=lambda tid, outcome, actor="studio":
                                  g.resolve_human_task(tid, outcome=outcome,
                                                       actor=actor))
        gw.run()

        # 制造挂起的人工任务
        m = make_action(SESSION, AGENT, "human.task.create",
                        params={"task_type": "approval",
                                "assignee_role": "finance_manager",
                                "context_ref": f"ctx_{SESSION}_inv"})
        m.seq = 1
        out = g.receive("agent", m.to_dict())
        task_id = out[0].payload["data"]["task_id"]
        assert g.sm.state == "SUSPENDED"

        # 页面渲染包含按钮与任务 id
        html = __import__("apa_core.studio", fromlist=["render_html"]) \
            .render_html(studio.sessions(), [])
        assert task_id in html
        assert "批准" in html and "驳回" in html
        assert "resolveTask" in html

        # 浏览器点击 ≡ POST resolve → 会话恢复
        server_port = studio.start_background()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server_port}/api/tasks/{task_id}/resolve",
            data=json.dumps({"outcome": "approve"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert json.loads(resp.read())["ok"] is True
        assert g.sm.state == "RUNNING"
        studio.shutdown()


@pytest.mark.e2e
class TestHumanApprovalDemo:
    def test_auto_approve(self):
        rc = self._run(["--auto", "approve"])
        assert rc == 0

    def test_auto_reject(self):
        rc = self._run(["--auto", "reject"])
        assert rc == 0

    @staticmethod
    def _run(extra):
        demo = APA_ROOT / "examples" / "human-approval" / "run.py"
        r = subprocess.run([sys.executable, str(demo), *extra],
                           capture_output=True, text=True, timeout=90)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "RESULT: OK" in r.stdout
        return r.returncode