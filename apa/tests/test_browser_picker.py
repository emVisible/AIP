"""浏览器元素拾取服务集成测试（需 playwright chromium）。

走真实注入链路：本地 HTTP 夹具页 → BrowserPickerService.start
→ 驱动服务自身浏览器实例点击/按键 → 断言选择器回传与 Esc 取消。
"""
import http.server
import os
import socketserver
import threading
import time
from functools import partial

import pytest

pytest.importorskip("playwright")

from apa_core.browser_picker import BrowserPickerService  # noqa: E402


PAGE = (
    "<html><head><meta charset='utf-8'></head><body>"
    "<button id='btn'>点我</button>"
    "</body></html>"
)


@pytest.fixture(scope="module")
def page_url():
    """本地静态服务器夹具：随机端口伺服单页 HTML。"""
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(PAGE)
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=d)
    handler.log_message = lambda *a, **kw: None
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/index.html"
    srv.shutdown()


@pytest.fixture()
def picker(page_url):
    s = BrowserPickerService()
    try:
        s.start(page_url)
    except Exception as e:  # chromium 缺失等环境问题 → 显式跳过
        pytest.skip(f"chromium unavailable: {e}")
    yield s
    s.stop()


def _wait_picked(s: BrowserPickerService, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = s.result()
        if r["picked"] is not None:
            return r["picked"]
        time.sleep(0.15)
    raise AssertionError("picked not delivered in time")


def test_start_validates_url():
    s = BrowserPickerService()
    with pytest.raises(Exception, match="http"):
        s.start("ftp://bad")


def test_click_pick_generates_selector(picker):
    # 通过服务自身浏览器实例驱动点击，覆盖 注入→高亮→选取→回传 全链路
    picker._page.click("#btn")
    picked = _wait_picked(picker)
    assert picked["tag"] == "button"
    assert "#btn" in picked["css"]
    assert "点我" in picked["text"]


def test_esc_cancels_pick(picker):
    picker._page.keyboard.press("Escape")
    deadline = time.time() + 5
    while time.time() < deadline:
        r = picker.result()
        if r["version"] > 1 and r["picked"] is None:
            return
        time.sleep(0.15)
    pytest.fail("Esc cancel not registered")


def test_restart_replaces_session(picker, page_url):
    # 单会话模型：重复 start 应静默替换且功能可用
    picker.start(page_url)
    picker._page.click("#btn")
    picked = _wait_picked(picker)
    assert "#btn" in picked["css"]
