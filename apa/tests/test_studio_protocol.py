"""H3 Studio Protocol v1 测试：RPC e2e + codegen 漂移门禁。"""
import pathlib

from fastapi.testclient import TestClient

from apa_core.api import create_app
from apa_core.studio_codegen import generate_ts


def _client(tmp_path):
    app = create_app(journals=[],
                     sessions_dir=str(tmp_path / "sessions"))
    return TestClient(app)


def test_rpc_session_roundtrip_envelope(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/studio/rpc", json={
        "id": "req-1", "method": "session.append",
        "params": {"sid": "s1", "kind": "message.user",
                   "payload": {"text": "hi"}}})
    body = r.json()
    assert body["id"] == "req-1" and body["ok"] is True
    assert body["result"]["event"]["seq"] == 1

    r = c.post("/api/studio/rpc", json={
        "id": "req-2", "method": "session.read", "params": {"sid": "s1"}})
    body = r.json()
    assert body["ok"]
    assert body["result"]["view"][0]["text"] == "hi"


def test_rpc_unknown_method_error_semantics(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/studio/rpc", json={
        "id": "x", "method": "nope.nope", "params": {}})
    err = r.json()["error"]
    assert err["code"] == "method_not_found"
    # 同名缺失参数 → invalid_params（区分语义）
    r = c.post("/api/studio/rpc", json={
        "id": "y", "method": "session.read", "params": {}})
    assert r.json()["error"]["code"] == "invalid_params"


def test_rpc_bgjob_cancel_not_found(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/studio/rpc", json={
        "id": "z", "method": "bgjobs.cancel",
        "params": {"job_id": "ghost", "actor": "__system__"}})
    assert r.json()["error"]["code"] == "conflict"


def test_rpc_tampered_session_maps_to_conflict(tmp_path):
    c = _client(tmp_path)
    c.post("/api/studio/rpc", json={
        "id": "a", "method": "session.append",
        "params": {"sid": "bad", "kind": "message.user",
                   "payload": {"text": "1"}}})
    p = tmp_path / "sessions" / "bad.jsonl"
    lines = p.read_text().splitlines()
    lines[0] = lines[0].replace('"seq": 1', '"seq": 7')
    p.write_text("\n".join(lines) + "\n")
    r = c.post("/api/studio/rpc", json={
        "id": "b", "method": "session.read", "params": {"sid": "bad"}})
    assert r.json()["error"]["code"] == "conflict"


def test_codegen_drift_gate():
    """生成产物必须与单源一致——手改 generated 文件会被此门禁拦下。"""
    out_path = (pathlib.Path(__file__).resolve().parents[1] /
                "frontend/src/shared/studioProtocol.ts")
    committed = out_path.read_text(encoding="utf-8")
    assert generate_ts() == committed, (
        "studioProtocol.ts 与 studio_protocol.py 漂移——"
        "请运行 python -m apa_core.studio_codegen 重新生成")
