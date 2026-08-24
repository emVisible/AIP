"""P18-M2 定时任务管理测试：cron_next 纯函数 + CRUD API + 热重载。"""
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apa_core.cron import CronError, next_after
from apa_core.serve import ServeApp


# ---- cron_next 纯函数 ---------------------------------------------------------

class TestCronNext:
    BASE = datetime(2026, 1, 31, 23, 59)   # 月末边界

    def test_every_minute(self):
        assert next_after("* * * * *", self.BASE) == \
            datetime(2026, 2, 1, 0, 0)

    def test_daily_at_hour(self):
        assert next_after("0 9 * * *", self.BASE) == \
            datetime(2026, 2, 1, 9, 0)

    def test_specific_minute_this_hour(self):
        base = datetime(2026, 3, 10, 8, 0)
        assert next_after("30 * * * *", base) == \
            datetime(2026, 3, 10, 8, 30)

    def test_feb_only_jumps_year(self):
        nxt = next_after("0 0 1 2 *", datetime(2026, 5, 1))
        assert (nxt.month, nxt.day) == (2, 1)
        assert nxt.year == 2027

    def test_impossible_expr_raises(self):
        with pytest.raises(CronError):
            next_after("0 0 30 2 *")       # 2月30日

    def test_strictly_after(self):
        base = datetime(2026, 4, 1, 12, 0)
        # 同一分钟不算（严格晚于）
        assert next_after("0 12 * * *", base) == \
            datetime(2026, 4, 2, 12, 0)


# ---- CRUD / 热重载 -------------------------------------------------------------

@pytest.fixture()
def app_env(tmp_path):
    from apa_core.api import create_app

    jobs_file = tmp_path / "scheduler.yaml"
    jobs_file.write_text("jobs: []\n", encoding="utf-8")
    procs = tmp_path / "procs"
    procs.mkdir()
    (procs / "job_demo.yaml").write_text(
        "process:\n  id: job_demo\n  mode: process\n"
        "  trigger: {type: manual}\n  steps:\n"
        "    - id: noop\n      action: context.update\n"
        "      params: {patch: {}}\n",
        encoding="utf-8")

    serve_app = ServeApp(
        journals=[str(tmp_path / "*.jsonl")],
        port=0, ws_port=None,
        processes_dir=str(procs),
        registry=__import__("apa_core.registry", fromlist=["x"])
        .load_registries(str(Path(__file__).resolve().parents[1]
                             / "registries" / "core.yaml")),
        mock_erp=False,
        runs_dir=str(tmp_path / "runs"),
        session_timeout_s=15.0,
    )
    n = serve_app.load_jobs(jobs_file)
    fast_app = create_app(
        journals=[str(tmp_path / "*.jsonl")],
        processes_dir=str(procs),
        ai_status={"mode": "rules_only"},
        dispatch_event=serve_app.dispatch_external_event,
        serve_app=serve_app,
    )
    return serve_app, TestClient(fast_app), jobs_file, n


class TestJobsCrud:
    def test_initial_empty(self, app_env):
        _, c, _, _ = app_env
        r = c.get("/api/jobs")
        assert r.status_code == 200 and r.json()["count"] == 0

    def test_save_persists_yaml(self, app_env):
        sa, c, jobs_file, _ = app_env
        r = c.post("/api/jobs/save", json={
            "id": "nightly", "kind": "cron", "process": "job_demo",
            "expr": "0 3 * * *"})
        assert r.status_code == 200
        doc = jobs_file.read_text(encoding="utf-8")
        assert "nightly" in doc and "0 3 * * *" in doc
        lst = c.get("/api/jobs").json()
        item = [j for j in lst["jobs"] if j["id"] == "nightly"][0]
        assert item["next_run"]          # cron_next 已计算

    def test_save_validation(self, app_env):
        _, c, _, _ = app_env
        bad_kind = c.post("/api/jobs/save", json={
            "id": "x", "kind": "wat", "process": "p"})
        assert bad_kind.status_code == 400
        no_id = c.post("/api/jobs/save", json={"kind": "cron"})
        assert no_id.status_code == 400

    def test_update_replaces_scheduler_entry(self, app_env):
        sa, c, _, _ = app_env
        c.post("/api/jobs/save", json={
            "id": "j1", "kind": "event", "process": "job_demo",
            "event": "e.one"})
        c.post("/api/jobs/save", json={          # 同 id 更新 event
            "id": "j1", "kind": "event", "process": "job_demo",
            "event": "e.two"})
        specs = sa.list_job_specs()["jobs"]
        ev = [j["event"] for j in specs if j["id"] == "j1"]
        assert ev == ["e.two"]
        # 调度器内事件任务确实替换（旧事件不再命中）
        fired_old = sa.scheduler.dispatch_event("e.one", {})
        assert fired_old == []

    def test_delete(self, app_env):
        sa, c, jobs_file, _ = app_env
        c.post("/api/jobs/save", json={
            "id": "gone", "kind": "event", "process": "job_demo",
            "event": "e.gone"})
        r = c.delete("/api/jobs/gone")
        assert r.json() == {"removed": "gone", "existed": True}
        assert "gone" not in jobs_file.read_text(encoding="utf-8")

    def test_run_now_triggers_session(self, app_env, tmp_path):
        sa, c, _, _ = app_env
        c.post("/api/jobs/save", json={
            "id": "manual1", "kind": "event", "process": "job_demo",
            "event": "e.manual"})
        r = c.post("/api/jobs/manual1/run")
        assert r.status_code == 200

        deadline = time.time() + 10
        done = False
        while time.time() < deadline and not done:
            for jf in Path(tmp_path).rglob("*.jsonl"):
                text = jf.read_text(encoding="utf-8")
                # 触发链路验证：会话到达任一终态即可
                if "outcome_summary" in text:
                    done = True
                    break
            if not done:
                time.sleep(0.1)
        assert done, "run-now 会话未产生终态 journal"


class TestFileWatch:
    def test_watch_triggers_on_new_file(self, app_env, tmp_path):
        sa, c, jobs_file, _ = app_env
        inbox = tmp_path / "inbox"
        inbox.mkdir()

        r = c.post("/api/jobs/save", json={
            "id": "watcher", "kind": "watch", "process": "job_demo",
            "expr": str(inbox) + "/*.csv"})
        assert r.status_code == 200

        # 首轮 tick 建立快照（空目录）
        sa.scheduler.tick()
        (inbox / "data.csv").write_text("a,b\n1,2\n")
        deadline = time.time() + 8
        done = False
        while time.time() < deadline and not done:
            sa.scheduler.tick()
            for jf in Path(tmp_path).rglob("*.jsonl"):
                if "outcome_summary" in jf.read_text(encoding="utf-8"):
                    done = True
                    break
            if not done:
                time.sleep(0.1)
        assert done, "文件监听未触发会话"

    def test_modify_fires_again(self, app_env, tmp_path):
        sa, c, _, _ = app_env
        inbox = tmp_path / "inbox2"
        inbox.mkdir()
        target = inbox / "f.txt"
        target.write_text("v1")

        c.post("/api/jobs/save", json={
            "id": "w2", "kind": "watch", "process": "job_demo",
            "expr": str(inbox) + "/*"})
        sa.scheduler.tick()          # 快照 v1

        fired = 0
        for round_no in range(2):
            time.sleep(0.02)         # 确保 mtime 变化
            target.write_text(f"v{round_no + 2}")
            fired += len(sa.scheduler.tick())
        assert fired == 2            # 每次修改各触发一次
