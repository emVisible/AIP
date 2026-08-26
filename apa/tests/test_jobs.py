"""H1 §4.2 jobs 生命周期测试（docs/harness-fusion.md 验收标准）。"""
import pytest

from apa_core.jobs import JobManager, JobNotFound, JobNotOwned


def test_triple_cancel_idempotent():
    m = JobManager()
    calls = []
    rec = m.start("spy", owner_session="s1",
                  on_cancel=lambda: calls.append(1))
    r1 = m.cancel(rec.id, "s1")
    r2 = m.cancel(rec.id, "s1")
    r3 = m.cancel(rec.id, "s1")
    assert r1.status == r2.status == r3.status == "cancelled"
    assert len(calls) == 1, "取消回调必须恰好执行一次"


def test_owner_fence_rejects_foreign_cancel():
    m = JobManager()
    rec = m.start("recorder", owner_session="sess-A")
    with pytest.raises(JobNotOwned):
        m.cancel(rec.id, "sess-B")
    assert m.get(rec.id).status == "running"
    # 系统级 actor 可越权（运维通道）
    m.cancel(rec.id, "__system__")
    assert m.get(rec.id).status == "cancelled"


def test_settlement_exactly_once():
    m = JobManager()
    settled = []
    rec = m.start("pick", owner_session="s", on_settle=lambda j: settled.append(j))
    m.complete(rec.id, result_ref="spills/x.json")
    m.complete(rec.id)
    m.complete(rec.id)
    assert len(settled) == 1
    assert m.get(rec.id).result_ref == "spills/x.json"


def test_complete_after_cancel_is_noop():
    m = JobManager()
    rec = m.start("k", owner_session="s")
    m.cancel(rec.id, "s")
    r = m.complete(rec.id)
    assert r.status == "cancelled"


def test_not_found_and_listing():
    m = JobManager()
    a = m.start("spy", owner_session="s")
    m.start("spy", owner_session="s")
    m.start("pick", owner_session="s")
    with pytest.raises(JobNotFound):
        m.get("nope")
    assert len(m.list(kind="spy")) == 2
    assert len(m.list(active_only=True)) == 3
    m.cancel(a.id, "s")
    assert len(m.list(active_only=True)) == 2
