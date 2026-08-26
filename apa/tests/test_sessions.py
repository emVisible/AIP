"""H1 §4.1 会话事件溯源测试（docs/harness-fusion.md 验收标准）。"""
import json

import pytest

from apa_core.sessions import (SessionStore, SessionTampered,
                               project_events)


@pytest.fixture()
def store(tmp_path):
    return SessionStore(tmp_path / "sessions")


def test_append_read_roundtrip_order(store):
    s1 = store.append("s1", "message.user", {"text": "你好"})
    s2 = store.append("s1", "message.assistant", {"text": "在的"})
    assert [s1["seq"], s2["seq"]] == [1, 2]
    events = store.read("s1")
    assert [e["seq"] for e in events] == [1, 2]
    assert events[0]["kind"] == "message.user"


def test_seq_continues_across_reopen(tmp_path):
    store_a = SessionStore(tmp_path)
    store_a.append("s", "message.user", {"text": "a"})
    # 模拟进程重启：新实例从磁盘尾恢复 seq
    store_b = SessionStore(tmp_path)
    e = store_b.append("s", "message.assistant", {"text": "b"})
    assert e["seq"] == 2


def test_tamper_gap_detected(store):
    store.append("x", "message.user", {"text": "1"})
    store.append("x", "message.assistant", {"text": "2"})
    path = store._path("x")
    lines = path.read_text().splitlines()
    lines[0] = json.dumps({**json.loads(lines[0]), "seq": 5})
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(SessionTampered, match="断裂"):
        store.read("x")


def test_torn_tail_tolerated_but_mid_corruption_raises(store):
    store.append("t", "message.user", {"text": "ok"})
    p = store._path("t")
    good = p.read_text()
    # 末行撕裂（崩溃残页）：容忍
    p.write_text(good + '{"seq": 2, "ts": 1, "ki')
    assert len(store.read("t")) == 1
    # 中间坏行：篡改
    p.write_text('{"broken"\n' + good)
    with pytest.raises(SessionTampered):
        store.read("t")


def test_projection_idempotent_and_draft_state_machine(store):
    sid = "proj"
    store.append(sid, "message.user", {"text": "监控竞品价格"})
    store.append(sid, "draft.created",
                 {"id": "d1", "yaml": "id: demo", "template": "price"})
    store.append(sid, "draft.approved", {"id": "d1"})
    store.append(sid, "message.assistant", {"text": "已批准并执行"})
    events = store.read(sid)
    v1 = project_events(events)
    v2 = project_events(events)
    assert v1 == v2
    msgs = [v for v in v1 if v["type"] == "message"]
    drafts = [v for v in v1 if v["type"] == "draft"]
    assert [m["role"] for m in msgs] == ["user", "apa"]
    assert len(drafts) == 1 and drafts[0]["state"] == "approved"


def test_unknown_kind_forward_compatible(store):
    store.append("fc", "future.kind", {"whatever": 1})
    assert project_events(store.read("fc")) == []


def test_list_sessions_meta(store):
    store.append("alpha", "message.user", {"text": "x"})
    store.append("beta", "message.user", {"text": "y"})
    listed = {s["id"]: s for s in store.list_sessions()}
    assert set(listed) == {"alpha.jsonl" and "alpha", "beta"}
    assert listed["alpha"]["events"] == 1


def test_illegal_session_id_rejected(store):
    from pytest import raises
    with raises(ValueError):
        store.append("../evil", "message.user", {})
