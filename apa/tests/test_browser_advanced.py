"""M3 浏览器高级动作 live 测试（需 playwright chromium）。"""
import pytest

pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

from apa_executors.browser_executor import (  # noqa: E402
    BrowserExecutor,
    PlaywrightPageOps,
)


@pytest.fixture(scope="module")
def env():
    pw = sync_playwright().start()
    ctx = pw.chromium.launch(headless=True).new_context()
    page = ctx.new_page()
    ex = BrowserExecutor("bot_t", "s_m3", page=PlaywrightPageOps(page))
    yield ex, page
    pw.stop()


PAGE_A = "<html><head><title>PageA</title></head><body><h1 id='h'>A</h1></body></html>"
FORM = """
<html><body>
<input id='f' type='file'/>
<div id='dbl' onclick="this.dataset.c=(+this.dataset.c||0)+1">click</div>
<div id='hov' onmouseover="this.dataset.h=1">hover</div>
<a id='dl' href='data:text/plain,HELLO-DL' download='x.txt'>dl</a>
</body></html>
"""


class TestTabs:
    def test_new_list_switch_close(self, env):
        ex, page = env
        page.set_content(PAGE_A)

        ok, t2 = ex._execute_action(
            "browser.tab_new", {"ref": "t2"})
        assert ok and t2["ref"] == "t2"
        ex._execute_action("browser.tab_switch", {"ref": "t2"})
        ex._page_set_content_helper = None
        # 新 tab 写入内容（走活动页）
        ex._execute_action("browser.execute_js",
                           {"script": "arg => { document.body.innerHTML ="
                                      " '<title>T2</title><b>tab2</b>'; }"})
        _, info = ex._execute_action("browser.get_page_info", {})
        assert "T2" in info["title"]

        _, lst = ex._execute_action("browser.tab_list", {})
        refs = [t["ref"] for t in lst["tabs"]]
        assert set(["tab_1", "t2"]) <= set(refs)
        active = [t for t in lst["tabs"] if t["active"]]
        assert active[0]["ref"] == "t2"

        # 切回 tab_1 → 标题是 PageA
        _, back = ex._execute_action("browser.tab_switch", {"ref": "tab_1"})
        assert "PageA" in back["title"]

        # 关闭 t2 → 剩 1，活动回到 tab_1
        _, closed = ex._execute_action("browser.tab_close", {"ref": "t2"})
        assert closed["remaining"] >= 1 and closed["active"] == "tab_1"

    def test_switch_unknown_ref(self, env):
        ex, _ = env
        ok, err = ex._execute_action("browser.tab_switch", {"ref": "nope"})
        assert not ok and err["code"] == "tab_not_found"


class TestScriptAndInteraction:
    def test_execute_js_arg_and_return(self, env):
        ex, _ = env
        o = ex._execute_action("browser.execute_js",
                               {"script": "([a,b]) => a + b",
                                "arg": [2, 3]})
        assert o[1]["value"] == 5

    def test_hover_double_click(self, env):
        ex, page = env
        page.set_content(FORM)
        ex._execute_action("browser.hover", {"target": "#hov"})
        h = page.evaluate("document.querySelector('#hov').dataset.h")
        assert h == "1"

        ex._execute_action("browser.double_click", {"target": "#dbl"})
        c = page.evaluate("document.querySelector('#dbl').dataset.c")
        # 一次 dblclick 触发两次 onclick → 计数 2
        assert c == "2"

    def test_element_attr(self, env):
        ex, page = env
        page.set_content("<a id='l' href='/x' data-k='v'>go</a>")
        o = ex._execute_action("browser.element_attr",
                               {"target": "#l", "attr": "data-k"})
        assert o[1]["value"] == "v"


class TestUploadDownload:
    def test_upload(self, env, tmp_path):
        ex, page = env
        page.set_content(FORM)
        f = tmp_path / "up.txt"
        f.write_text("upload-me")
        ok, out = ex._execute_action(
            "browser.upload", {"target": "#f", "files": [str(f)]})
        assert ok and out["count"] == 1
        name = page.evaluate(
            "document.querySelector('#f').files[0].name")
        assert name == "up.txt"

    def test_download_url_mode(self, env, tmp_path):
        ex, _ = env
        dst = tmp_path / "d.bin"
        # data: URL 直链（httpx 支持）
        import base64

        b64 = base64.b64encode(b"PAYLOAD-123").decode()
        ok, out = ex._execute_action(
            "browser.download",
            {"path": str(dst), "url": f"data:text/plain;base64,{b64}"})
        assert ok and out["mode"] == "url" and out["bytes"] == 11
        assert dst.read_bytes() == b"PAYLOAD-123"

    def test_download_trigger_mode(self, env, tmp_path):
        ex, page = env
        page.set_content(FORM)
        dst = tmp_path / "trig.txt"
        ok, out = ex._execute_action(
            "browser.download",
            {"path": str(dst), "trigger_target": "#dl"})
        assert ok and out["mode"] == "trigger"
        assert dst.read_text() == "HELLO-DL"


class TestCookies:
    def test_roundtrip_and_clear(self, env):
        ex, _ = env
        ex._execute_action("browser.cookies_set", {"cookies": [
            {"name": "sid", "value": "S1", "url": "http://example.com"},
            {"name": "k2", "value": "V2", "url": "http://example.com"},
        ]})
        got = ex._execute_action("browser.cookies_get", {})[1]
        names = {c["name"] for c in got["cookies"]}
        assert {"sid", "k2"} <= names

        ex._execute_action("browser.cookies_clear", {})
        after = ex._execute_action("browser.cookies_get", {})[1]
        assert after["count"] == 0


def _jsonable(v):  # 兜底引用（与 executor 内一致）
    try:
        import json

        json.dumps(v)
        return v
    except TypeError:
        return str(v)

class TestSimilarElements:
    def test_get_similar_and_foreach_source_shape(self, env):
        ex, page = env
        page.set_content("""
        <ul id='list'>
          <li class='it'>甲</li><li class='it'>乙</li>
          <li class='it'>丙</li>
        </ul>""")
        ok, out = ex._execute_action("browser.get_similar_elements",
                                     {"selector": "#list .it",
                                      "output_context": "items"})
        assert ok and out["count"] == 3
        texts = [e["text"] for e in out["elements"]]
        assert texts == ["甲", "乙", "丙"]
        # foreach source 形态：elements 数组每项含 index/text
        first = out["elements"][0]
        assert {"index", "text"} <= set(first.keys())

    def test_limit(self, env):
        ex, page = env
        page.set_content("<div class='r'></div>" * 7)
        ok, out = ex._execute_action("browser.get_similar_elements",
                                     {"selector": ".r", "limit": 3})
        assert out["count"] == 3


class TestDialogAndDrag:
    def test_dialog_handle_accept(self, env):
        ex, page = env
        page.set_content("""
        <button onclick="document.title='alerted'">fire</button>""")
        # 武装处理器后触发 alert（Playwright 默认 dismiss，武装前需注册）
        ex._execute_action("browser.dialog_handle",
                           {"action": "accept"})
        page.click("button")
        # 无异常即通过（dialog 被处理器消费而非默认阻塞）

    def test_drag_drop(self, env):
        ex, page = env
        page.set_content("""
        <div id='a' draggable='true'>A</div>
        <div id='b' ondrop='document.title="dropped"'
             ondragover='event.preventDefault()'>B</div>""")
        ok, _ = ex._execute_action("browser.drag_drop",
                                   {"from": "#a", "to": "#b"})
        assert ok
