"""H2 测试：计划态确认门 + spill 引擎级集成（docs/harness-fusion.md §4.3/§5）。"""
import pytest
from fastapi.testclient import TestClient

import apa_core.spill as spill_mod
from apa_core.process import ProcessEngine, build_process
from apa_core.spill import SpillStore


# ---- H2-a 计划态确认门 -------------------------------------------------------

@pytest.fixture()
def gate_client(client, core_services):
    return client, str(core_services.sessions._dir)


def _mk_draft(client: TestClient, sid: str, did: str):
    client.post(f"/api/sessions/{sid}/append",
                json={"kind": "draft.created",
                      "payload": {"id": did, "yaml": "id: x"}})


def _approve(client: TestClient, sid: str, did: str):
    client.post(f"/api/sessions/{sid}/append",
                json={"kind": "draft.approved", "payload": {"id": did}})


def _save(client: TestClient, sid="", did=""):
    return client.post("/api/processes/save", json={
        "id": "p1", "yaml": "id: p1",
        "session_id": sid, "draft_id": did})


def test_unapproved_draft_cannot_save_or_test(gate_client):
    c, _ = gate_client
    _mk_draft(c, "s1", "d1")   # 仅创建，未批准
    r = _save(c, "s1", "d1")
    assert r.status_code == 409 and "未获批准" in r.json()["detail"]
    r = c.post("/api/processes/test", json={
        "yaml": "id: x", "event": "", "data": {},
        "session_id": "s1", "draft_id": "d1"})
    assert r.status_code == 409


def test_created_but_not_approved_distinct_from_approved(gate_client):
    c, _ = gate_client
    _mk_draft(c, "s2", "d2")
    assert _save(c, "s2", "d2").status_code == 409
    _approve(c, "s2", "d2")
    assert _save(c, "s2", "d2").status_code == 200


def test_missing_session_with_draft_id_rejected(gate_client):
    c, _ = gate_client
    r = _save(c, "", "ghost")
    assert r.status_code == 409 and "溯源缺失" in r.json()["detail"]


def test_manual_flow_without_provenance_unaffected(gate_client):
    c, _ = gate_client
    assert _save(c).status_code == 200   # 手工流程不受确认门约束


# ---- H2-b spill 引擎级集成 ---------------------------------------------------

def _engine_with_steps(tmp_path, steps, responses, threshold=100,
                       max_actions=50):
    spill_mod._default_store = SpillStore(tmp_path / "spills",
                                          threshold=threshold)
    proc = build_process({"process": {
        "id": "t", "mode": "process", "trigger": {"type": "manual"},
        "max_actions": max_actions, "steps": steps}})
    eng = ProcessEngine(proc, lambda a, p: responses[a])
    eng.run.scopes["event"] = {}
    eng._run_from(0)
    return eng


def test_engine_spill_param_replaces_big_result(tmp_path):
    big = {"columns": ["a"], "count": 500,
           "rows": [{"a": i} for i in range(500)]}
    steps = [{"id": "big", "action": "browser.extract_table",
              "params": {"spill": True}}]
    eng = _engine_with_steps(tmp_path, steps,
                             {"browser.extract_table": (True, big)})
    stored = eng.run.scopes["steps"]["big"]
    assert stored["__spill__"] is True and stored["truncated"] is True
    # 原文可经内置动作回读
    ref = stored["spill_ref"]
    steps2 = [{"id": "read", "action": "context.spill_read",
               "params": {"ref": ref}}]
    eng2 = _engine_with_steps(tmp_path, steps2,
                              {"browser.extract_table": (True, big)})
    assert eng2.run.scopes["steps"]["read"]["count"] == 500


def test_engine_without_spill_param_unchanged(tmp_path):
    big = {"rows": [{"a": i} for i in range(500)], "count": 500}
    steps = [{"id": "big", "action": "browser.extract_table"}]
    eng = _engine_with_steps(tmp_path, steps,
                             {"browser.extract_table": (True, big)})
    stored = eng.run.scopes["steps"]["big"]
    assert stored.get("__spill__") is None and stored["count"] == 500


def test_builtin_spill_read_consumes_no_action_budget(tmp_path):
    # 预置一个真实可回读的 spill
    store = SpillStore(tmp_path / "spills", threshold=100)
    ref_obj, _ = store.maybe_spill("browser.extract_table",
                                   {"rows": [{"a": i} for i in range(200)],
                                    "count": 200})
    steps = [
        {"id": "r", "action": "context.spill_read",
         "params": {"ref": ref_obj["spill_ref"]}},
        {"id": "real", "action": "any.real"},
    ]
    sent = []

    def fake_send(a, p):
        sent.append(a)
        return True, {}

    spill_mod._default_store = SpillStore(tmp_path / "spills")
    proc = build_process({"process": {
        "id": "t", "mode": "process", "trigger": {"type": "manual"},
        "max_actions": 1, "steps": steps}})
    eng = ProcessEngine(proc, fake_send)
    eng.run.scopes["event"] = {}
    eng._run_from(0)
    assert sent == ["any.real"], "内置回读不应消耗动作预算/触达 send_fn"
    assert eng.run.scopes["steps"]["r"]["count"] == 200
    assert eng.run.actions_sent == 1, "预算只应被真实动作消耗"
