"""浏览器拾取扩展通道 API 测试（无需 chromium）。"""
import io
import zipfile


from fastapi.testclient import TestClient  # noqa: E402

from apa_core.api import create_app  # noqa: E402


def _client() -> TestClient:
    return TestClient(create_app(journals=[]))


def test_extension_event_ingest_and_result_passthrough():
    c = _client()
    r = c.post("/api/browser_pick/event", json={
        "tag": "button", "text": "提交", "css": "#submit > span"})
    assert r.status_code == 200 and r.json() == {"ok": True}

    res = c.get("/api/browser_pick/result").json()
    assert res["active"] is True
    assert res["picked"]["tag"] == "button"
    assert res["picked"]["css"] == "#submit > span"


def test_protocol_v2_kind_payloads_passthrough():
    """协议 v2：element / list_done 载荷 dict 原样透传，不丢字段。"""
    c = _client()
    element = {
        "kind": "element",
        "locator": {"css": "#app >>> .row", "xpath": None,
                    "in_shadow": True},
        "meta": {"tag": "div", "text": "x", "attrs": {},
                 "url": "http://t/"},
    }
    assert c.post("/api/browser_pick/event", json=element).json() == {"ok": True}
    got = c.get("/api/browser_pick/result").json()["picked"]
    assert got["kind"] == "element"
    assert got["locator"]["in_shadow"] is True

    done = {
        "kind": "list_done", "row_css": ".item",
        "columns": {"title": ".t", "link": "a"},
        "match_count": 12, "preview": [["a", "b"]],
    }
    assert c.post("/api/browser_pick/event", json=done).json() == {"ok": True}
    got = c.get("/api/browser_pick/result").json()["picked"]
    assert got["kind"] == "list_done" and got["match_count"] == 12
    assert got["columns"]["title"] == ".t"


def test_event_rejects_non_object():
    c = _client()
    r = c.post("/api/browser_pick/event", json=[1, 2])
    assert r.status_code == 422


def test_extension_download_zip_contains_bundle():
    c = _client()
    r = c.get("/api/browser_pick/extension/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert {"manifest.json", "background.js",
            "content.js", "popup.html", "popup.js"} <= names
    manifest = zf.read("manifest.json").decode()
    assert '"manifest_version": 3' in manifest
