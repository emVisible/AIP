"""录制器真实浏览器 E2E（需 playwright chromium）。

实证要点（调试结论，防止回归）：
- set_content/硬导航会清除 document/window 级监听器；
- init_script 挂载的处理器不参与真实输入分发；
- 唯一可靠注入 = 页面就绪后 evaluate；多次注入用世代号去重。
"""
import pytest

from apa_core.recorder import RecorderSession, events_to_process

pw = pytest.importorskip("playwright")

HTML = """
<html><body>
  <input id='user' name='username'/>
  <select name='city'><option value='SH'>SH</option>
    <option value='BJ'>BJ</option></select>
  <button data-apa-id='go-btn' onclick="document.title='done'">GO</button>
</body></html>
"""


@pytest.fixture()
def recorder():
    sess = RecorderSession("about:blank", headless=True)
    sess.start()
    page = sess._page
    page.set_content(HTML)
    sess.reinject()
    yield sess, page
    sess.stop()


class TestRealRecording:
    def test_captures_all_three_kinds(self, recorder):
        sess, page = recorder
        page.fill("#user", "alice")
        page.select_option("[name='city']", "BJ")
        page.click("[data-apa-id='go-btn']")
        page.wait_for_timeout(600)

        kinds = {e["kind"] for e in sess.events}
        assert {"input", "select", "click"} <= kinds

    def test_yaml_roundtrip_exact(self, recorder):
        import yaml as _y

        sess, page = recorder
        page.fill("#user", "alice")
        page.select_option("[name='city']", "BJ")
        page.click("[data-apa-id='go-btn']")
        page.wait_for_timeout(600)

        doc = _y.safe_load(_y.safe_dump(
            events_to_process(sess.events, process_id="recorded_e2e"),
            allow_unicode=True, sort_keys=False))
        by_action: dict = {}
        for s in doc["process"]["steps"]:
            by_action.setdefault(s["action"], []).append(s["params"])

        assert by_action["browser.input"] == [
            {"target": "#user", "value": "alice"}]
        assert by_action["browser.select_option"] == [
            {"target": "[name='city']", "value": "BJ"}]
        assert by_action["browser.click"] == [
            {"target": "[data-apa-id='go-btn']"}]

    def test_generation_dedup(self, recorder):
        """重复 reinject 不产生重复事件（世代号过滤）。"""
        sess, page = recorder
        sess.reinject()  # 第二代监听器
        page.click("[data-apa-id='go-btn']")
        page.wait_for_timeout(500)
        clicks = [e for e in sess.events if e.get("kind") == "click"]
        assert len(clicks) == 1