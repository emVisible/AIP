"""H3 二期测试：NotificationHub / rpc_table / SSE 下行端点。"""
import json

import pytest
from fastapi.testclient import TestClient

from apa_core.api import create_app
from apa_core.core_services import CoreServices


# ---- NotificationHub ----

def test_hub_publish_subscribe_roundtrip():
    svc = CoreServices(sessions=":memory:")
    q = svc.notifications.subscribe()
    svc.notify("run.step", {"action": "a", "status": "ok"})
    evt = q.get_nowait()
    assert evt["method"] == "run.step" and evt["payload"]["action"] == "a"


def test_hub_unsubscribe_stops_delivery():
    svc = CoreServices(sessions=":memory:")
    q = svc.notifications.subscribe()
    svc.notifications.unsubscribe(q)
    svc.notify("run.outcome", {"outcome": "success"})
    assert q.empty()


def test_hub_overflow_drops_oldest_not_raises():
    from apa_core.core_services import NotificationHub

    hub = NotificationHub(maxsize=2)
    q = hub.subscribe()
    for i in range(5):
        hub.publish("run.step", {"i": i})
    got = [q.get_nowait() for _ in range(2)]
    assert got[0]["payload"]["i"] == 3, "丢最旧，保留最新两条"
    assert got[1]["payload"]["i"] == 4


# ---- rpc_table（容器注册表与 api 层等价） ----

def test_rpc_table_handlers(tmp_path):
    svc = CoreServices(sessions=str(tmp_path / "s"))
    table = svc.rpc_table()
    r = table["session.append"](
        {"sid": "x", "kind": "message.user", "payload": {"text": "hi"}})
    assert r["event"]["seq"] == 1
    read = table["session.read"]({"sid": "x"})
    assert read["view"][0]["text"] == "hi"
    jobs = table["bgjobs.list"]({})
    assert jobs["jobs"] == []


# ---- SSE 下行端点（真实流） ----

def test_sse_endpoint_contract_registered(tmp_path):
    """端点契约锁定；SSE 真实流语义经 curl 手动验收
    （TestClient 不逐块冲刷无限流，属工具边界，见 CHANGELOG）。"""
    services = CoreServices(sessions=str(tmp_path / "s"))
    app = create_app(journals=[], sessions_dir=str(tmp_path / "s"),
                     services=services)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/studio/events" in paths


def test_hub_publish_after_client_close_no_error(tmp_path):
    """客户端断开后 publish 不抛错（订阅表已清理）。"""
    services = CoreServices(sessions=str(tmp_path / "s"))
    q = services.notifications.subscribe()
    services.notifications.unsubscribe(q)
    services.notify("run.outcome", {"outcome": "success"})


def test_testrun_emits_live_run_steps(client, core_services):
    """H3 三期验收：试运行期间 run.step 经总线实时可订阅。"""
    q = core_services.notifications.subscribe()
    try:
        r = client.post("/api/studio/rpc", json={
            "id": "live", "method": "process.test",
            "params": {"yaml": "id: x", "event": "", "data": {}}})
        assert r.json()["ok"] is True
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        steps = [e for e in events if e["method"] == "run.step"]
        assert len(steps) == 1
        assert steps[0]["payload"]["action"] == "demo.a"
        assert steps[0]["payload"]["status"] == "ok"
    finally:
        core_services.notifications.unsubscribe(q)


def test_gate_refusal_emits_approval_elicitation(client, core_services):
    """计划态门拒绝时同步推送 approval.elicit（UI ticker 数据源）。"""
    q = core_services.notifications.subscribe()
    try:
        client.post("/api/sessions/s9/append", json={
            "kind": "draft.created",
            "payload": {"id": "d9", "yaml": "id: x"}})
        r = client.post("/api/studio/rpc", json={
            "id": "g1", "method": "process.save",
            "params": {"id": "p", "yaml": "id: p",
                       "session_id": "s9", "draft_id": "d9"}})
        assert r.json()["ok"] is False
        evts = []
        while not q.empty():
            evts.append(q.get_nowait())
        elicits = [e for e in evts if e["method"] == "approval.elicit"]
        assert len(elicits) == 1
        assert elicits[0]["payload"]["draft_id"] == "d9"
    finally:
        core_services.notifications.unsubscribe(q)


def test_settings_get_update_roundtrip(client, core_services):
    """H7b：get 视图结构 / update 热应用 / env-owned 拒写映射。"""
    r = client.post("/api/studio/rpc", json={
        "id": "s1", "method": "settings.get", "params": {}})
    body = r.json()
    assert body["ok"], f"get 失败: {json.dumps(body, ensure_ascii=False)}"
    assert body["result"]["version"] == 1
    assert isinstance(body["result"]["env_owned"], list)
    assert "llm" in body["result"]["settings"]

    # 热应用：改 model 后容器内即时生效
    r = client.post("/api/studio/rpc", json={
        "id": "s2", "method": "settings.update",
        "params": {"patch": {"llm": {"model": "hot-switched"}}}})
    assert r.json()["ok"] is True
    assert core_services.settings.current.llm.model == "hot-switched"

    # 用户层文件已双写
    user_yaml = core_services.settings.user_path.read_text()
    assert "hot-switched" in user_yaml


def test_settings_update_rejects_unknown_and_env_owned(
        client, legacy_env):
    r = client.post("/api/studio/rpc", json={
        "id": "a", "method": "settings.update",
        "params": {"patch": {"nope": 1}}})
    err = r.json()["error"]
    assert err["code"] == "invalid_params" and "未知/禁写键" in err["message"]

    # env-owned 路径拒绝写回（提示改环境变量）
    r = client.post("/api/studio/rpc", json={
        "id": "c", "method": "settings.update",
        "params": {"patch": {"data": {"root": "zzz"}}}})
    err = r.json()["error"]
    assert err["code"] == "invalid_params"
    assert "APA_DATA_DIR" in err["message"]


def test_usage_summary_zero_state(client):
    r = client.post("/api/studio/rpc", json={
        "id": "u", "method": "usage.summary",
        "params": {"session_id": "nonexistent"}})
    body = r.json()
    assert body["ok"] is True
    assert body["result"]["calls"] == 0
    assert body["result"]["total_tokens"] == 0
