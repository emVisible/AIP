"""录制器纯函数层测试（无浏览器依赖）。"""
import pytest

from apa_core.recorder import css_selector, event_to_step, events_to_process


class TestCssSelector:
    def test_data_apa_id_priority(self):
        el = {"tag": "button", "id": "btn1",
              "attrs": {"data-apa-id": "submit", "name": "s"}}
        assert css_selector(el) == "[data-apa-id='submit']"

    def test_id_fallback(self):
        el = {"tag": "div", "id": "main", "attrs": {}}
        assert css_selector(el) == "#main"

    def test_name_attr(self):
        el = {"tag": "input", "attrs": {"name": "username"}}
        assert css_selector(el) == "[name='username']"

    def test_aria_label(self):
        el = {"tag": "button", "attrs": {"aria-label": "关闭"}}
        assert css_selector(el) == "[aria-label='关闭']"

    def test_class_path(self):
        el = {"tag": "span", "attrs": {"class": "price-tag bold"}}
        assert css_selector(el) == "span.price-tag"

    def test_bare_tag(self):
        assert css_selector({"tag": "td", "attrs": {}}) == "td"


class TestEventToStep:
    def test_navigate(self):
        step = event_to_step({"kind": "navigate", "url": "https://x.com"}, 3)
        assert step == {
            "id": "s03_navigate",
            "action": "browser.navigate",
            "params": {"url": "https://x.com"},
        }

    def test_click(self):
        el = {"tag": "button", "attrs": {"name": "submit"}}
        step = event_to_step({"kind": "click", "element": el}, 1)
        assert step["action"] == "browser.click"
        assert step["params"]["target"] == "[name='submit']"

    def test_input(self):
        el = {"tag": "input", "attrs": {"name": "q"}}
        step = event_to_step(
            {"kind": "input", "element": el, "value": "hello"}, 2)
        assert step["action"] == "browser.input"
        assert step["params"] == {"target": "[name='q']", "value": "hello"}

    def test_select(self):
        el = {"tag": "select", "attrs": {"name": "city"}}
        step = event_to_step(
            {"kind": "select", "element": el, "value": "SH"}, 4)
        assert step["action"] == "browser.select_option"
        assert step["params"]["value"] == "SH"

    def test_unknown_kind_returns_none(self):
        assert event_to_step({"kind": "hover"}, 9) is None


class TestEventsToProcess:
    def test_full_flow(self):
        events = [
            {"kind": "navigate", "url": "https://a.com"},
            {"kind": "click",
             "element": {"tag": "a", "attrs": {"href": "/login"}}},
            {"kind": "navigate", "url": "https://a.com/login"},
            {"kind": "input",
             "element": {"tag": "input", "attrs": {"name": "user"}},
             "value": "bob"},
            {"kind": "click",
             "element": {"tag": "button", "attrs": {"data-apa-id": "go"}}},
        ]
        proc = events_to_process(events, process_id="login_flow")
        p = proc["process"]
        assert p["id"] == "login_flow"
        # 中间导航被合并丢弃，首导航保留
        kinds = [s["action"].split(".")[1] for s in p["steps"]]
        assert kinds == ["navigate", "click", "input", "click"]
        assert p["max_actions"] >= len(p["steps"])

    def test_empty_events(self):
        proc = events_to_process([], process_id="empty")
        assert proc["process"]["steps"] == []
        assert proc["process"]["trigger"]["type"] == "manual"

    def test_event_trigger(self):
        proc = events_to_process([], process_id="x",
                                 trigger_name="webhook.received")
        assert proc["process"]["trigger"] == {
            "type": "event", "name": "webhook.received"}

    @pytest.mark.parametrize("pid", ["flow_a", "b-2"])
    def test_ids_stable(self, pid):
        proc = events_to_process([{ "kind": "navigate", "url": "u" }], process_id=pid)
        assert proc["process"]["id"] == pid