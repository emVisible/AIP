"""Phase 8 测试：Cron 解析 / Scheduler 双触发 / ProcessRunner 启动器 / apa CLI。"""
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

from aip import AIPPeer, FakeClock, make_action

from apa_core.cron import CronError, CronExpr
from apa_core.launcher import run_process
from apa_core.mock_erp import MockERP
from apa_core.scheduler import Scheduler, SchedulerError

APA_ROOT = Path(__file__).resolve().parent.parent


class TestCron:
    def test_every_day_at_time(self):
        c = CronExpr("30 9 * * *")
        assert c.matches(datetime(2026, 8, 22, 9, 30))
        assert not c.matches(datetime(2026, 8, 22, 9, 31))

    def test_step_minutes(self):
        c = CronExpr("*/15 * * * *")
        assert c.matches(datetime(2026, 1, 1, 14, 0))
        assert not c.matches(datetime(2026, 1, 1, 14, 20))

    def test_weekday_range_python_semantics(self):
        c = CronExpr("0 8 * * 0-4")   # 周一(0)～周五(4)
        assert c.matches(datetime(2026, 8, 17, 8, 0))   # 周一
        assert not c.matches(datetime(2026, 8, 22, 8, 0))  # 周六

    def test_list_and_ranges(self):
        c = CronExpr("5,10-12,*/20 6 1,15 * *")
        assert c.minute == frozenset({0, 5, 10, 11, 12, 20, 40})
        assert c.day == frozenset({1, 15})

    def test_invalid_expressions(self):
        for bad in ("* * * *", "* * * * * *", "60 * * * *",
                    "*/0 * * * *", "a * * * *", "5-2 * * * *"):
            with pytest.raises(CronError):
                CronExpr(bad)


class TestScheduler:
    def test_cron_fires_once_per_minute(self):
        clock = FakeClock(start_ms=0)
        sched = Scheduler(clock=clock)
        fired = []
        sched.add_cron("every_min", "* * * * *",
                       lambda job: fired.append(job["fired_ms"]))
        # 同一分钟内多次 tick → 只发一次
        for _ in range(5):
            sched.tick()
        assert len(fired) == 1
        # 跨入下一分钟 → 再发一次
        clock.advance(61_000)
        fired2 = sched.tick()
        assert len(fired) == 2 and len(fired2) == 1

    def test_cron_window_skipped_until_match(self):
        import datetime as _dt
        now_dt = _dt.datetime.now().replace(second=5, microsecond=0)
        clock_t = FakeClock(start_ms=int(now_dt.timestamp() * 1000))
        sched = Scheduler(clock=clock_t)
        fired = []
        sched.add_cron("half_past", "30 * * * *",
                       lambda job: fired.append(job))
        pre = sched.tick()
        target = now_dt.replace(minute=30, second=0)
        if target <= now_dt:
            target += _dt.timedelta(hours=1)
        clock_t.advance(int((target - now_dt).total_seconds() * 1000) + 100)
        got = sched.tick()
        if not pre:
            assert len(got) == 1 and got[0]["spec"] == "30 * * * *"
        else:
            assert len(pre) == 1   # 起点即 :30 的罕见情形
        # 同一分钟内再 tick → 去重不触发；逐分钟推进到下一个 :30 → 再次触发
        clock_t.advance(59_000)
        assert sched.tick() == []
        refired = False
        for _ in range(62):          # 一小时内必命中
            clock_t.advance(60_000)
            if sched.tick():
                refired = True
                break
        assert refired

    def test_event_dispatch_with_filter(self):
        sched = Scheduler()
        hits = []
        sched.add_event("inv_arrived", "erp.invoice.received",
                        lambda job: hits.append(job["data"]),
                        data_filter={"tenant": "corp_x"})
        sched.dispatch_event("other.event", {})
        sched.dispatch_event("erp.invoice.received", {"tenant": "corp_y"})
        assert hits == []
        sched.dispatch_event("erp.invoice.received", {"tenant": "corp_x",
                                                      "amount": 9})
        assert hits == [{"tenant": "corp_x", "amount": 9}]

    def test_bad_event_name_and_cron(self):
        sched = Scheduler()
        with pytest.raises(SchedulerError):
            sched.add_event("j", "noDots", lambda j: None)
        with pytest.raises(SchedulerError):
            sched.add_cron("j", "* * * *", lambda j: None)

    def test_remove_job(self):
        sched = Scheduler()
        sched.add_event("j1", "a.b.c", lambda j: None)
        assert sched.remove("j1") is True
        assert sched.remove("j1") is False
        assert sched.dispatch_event("a.b.c", {}) == []


class TestProcessLauncher:
    def test_run_process_end_to_end(self, tmp_path):
        """launcher.run_process：process.yaml + 复合执行器 → 一次到终态。"""
        erp = MockERP(seed_orders=[{"id": "PO-LAUNCH-1", "status": "pending"}])
        port = erp.start()

        from apa_executors.api_executor import APIExecutor
        from apa_sdk.composite import CompositeExecutor

        def make_executors():
            # 每个 runner 独立会话；register() 会把模块 peer 注入为 router 的
            router = CompositeExecutor("bot_launch",
                                       "s_launch_po_auto_approval")
            api_mod = APIExecutor("bot_launch", "s_launch_po_auto_approval",
                                  base_url=f"http://127.0.0.1:{port}")
            router.register(("api", "erp"), api_mod)
            return [(("api", "erp"), router)]

        result = run_process(
            APA_ROOT / "examples" / "po-approval" / "process.yaml",
            "erp.order.approval_requested",
            {"context": "ctx_s_launch_po_auto_approval_order",
             "notify_url": f"http://127.0.0.1:{port}/notify"},
            executors=make_executors(),
            journal_dir=tmp_path,
            session_prefix="s_launch",
            seed_contexts=[("order", {"order_id": "PO-LAUNCH-1",
                                      "amount": 45000,
                                      "vendor": "供应商L"})],
        )
        assert result["outcome"] == "success"
        assert result["gateway_state"] == "COMPLETED"
        assert any(r.get("path", "").endswith("/approve")
                   for r in erp.requests)
        assert any(r.get("path") == "/notify" for r in erp.requests)
        erp.stop()


def agent_peer_handler(peer, pending, engine):
    def on_message(raw):
        cls, msg = peer.handle(raw)
        if cls != "accept":
            return
        if msg.type == "event":
            p = msg.payload
            engine.on_trigger(p.get("name", ""), p.get("data") or {})
        elif msg.type == "result" and msg.in_reply_to in pending:
            pending[msg.in_reply_to] = msg.payload
    return on_message


class _Shell:
    def __init__(self, on_message, peer) -> None:
        self.on_message = on_message
        self.peer = peer


class TestApaCli:
    def test_analytics_subprocess(self, tmp_path):
        jpath = tmp_path / "cli.jsonl"
        jpath.write_text(json.dumps({
            "kind": "state", "ts": int(time.time() * 1000),
            "session": "s_cli", "to": "COMPLETED"}) + "\n")
        venv_py = Path(sys.executable)
        r = subprocess.run(
            [str(venv_py), "-m", "apa_core.cli", "analytics",
             "--journals", str(jpath)],
            capture_output=True, text=True, timeout=30,
            env={"PYTHONPATH": str(APA_ROOT / "packages" / "apa-core") +
                 ":" + str(APA_ROOT / "sdk" / "python"),
                 "PATH": "/usr/bin:/bin"})
        assert r.returncode == 0, r.stderr
        assert "APA Analytics" in r.stdout