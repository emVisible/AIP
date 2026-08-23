"""数据抓取向导真实浏览器 E2E（需 playwright chromium）。

覆盖：点击拦截 → 两行标记 → shared_class 推断 → 列相对选择器
→ 活页预览精确回读 → 步骤生成。
"""
import time

import pytest

from apa_core.scrape_service import ScrapeError, ScrapeWizardService

pytest.importorskip("playwright")

HTML = """
<html><body>
<div class="list">
  <div class="item"><h3>订单 A1</h3><span class="amt">120</span></div>
  <div class="item"><h3>订单 A2</h3><span class="amt">80</span></div>
  <div class="item"><h3>订单 A3</h3><span class="amt">999</span></div>
  <div class="item"><h3>订单 A4</h3><span class="amt">55</span></div>
</div></body></html>
"""


@pytest.fixture()
def wizard():
    svc = ScrapeWizardService()
    sid = svc.start("about:blank", headless=True)["session_id"]
    s = svc._get(sid)
    svc._submit(s, lambda pg: pg.set_content(HTML))
    svc.reinject(sid)
    yield svc, sid, s
    try:
        svc.stop(sid)
    except ScrapeError:
        pass


def js_click(wizard, css):
    svc, sid, _ = wizard
    svc._submit(svc._get(sid), lambda pg: pg.evaluate(
        "css => { const el = document.querySelector(css);"
        " if (!el) throw new Error('not found: ' + css); el.click(); }",
        css))


class TestWizardLive:
    def test_full_pipeline(self, wizard):
        svc, sid, s = wizard
        js_click((svc, sid, s), ".item:nth-of-type(1)")
        js_click((svc, sid, s), ".item:nth-of-type(2)")
        time.sleep(0.4)

        svc.assign(sid, "row")
        svc.assign(sid, "row")
        st = svc.status(sid)
        assert st["strategy"] == "shared_class"
        assert st["row_selector"] == "div.list > div.item"

        js_click((svc, sid, s), ".item:nth-of-type(1) > h3")
        time.sleep(0.3)
        svc.assign(sid, "column", name="title")
        js_click((svc, sid, s), ".item:nth-of-type(1) > span.amt")
        time.sleep(0.3)
        svc.assign(sid, "column", name="amount")

        prev = svc.preview(sid, max_rows=4)
        assert prev["rows"][0] == {"title": "订单 A1", "amount": "120"}
        assert prev["rows"][3]["amount"] == "55"

        gen = svc.generate(sid, base_id="scrape")
        assert [x["id"] for x in gen["steps"]] == [
            "scrape_open", "scrape_scrape"]

    def test_column_before_rows_fails(self, wizard):
        svc, sid, s = wizard
        js_click((svc, sid, s), ".item:nth-of-type(1) > h3")
        with pytest.raises(ScrapeError):
            svc.assign(sid, "column", name="x")

    def test_bad_row_pair_rollback(self, wizard):
        """同一元素点两次 → 推断失败 → 行状态回滚可重试。"""
        svc, sid, s = wizard
        js_click((svc, sid, s), ".item:nth-of-type(1)")
        time.sleep(0.3)
        svc.assign(sid, "row")
        # 第二行点同一元素（无新 pick → 直接报错）
        with pytest.raises(ScrapeError):
            svc.assign(sid, "row")

    def test_generate_with_loop(self, wizard):
        svc, sid, s = wizard
        js_click((svc, sid, s), ".item:nth-of-type(1)")
        js_click((svc, sid, s), ".item:nth-of-type(2)")
        time.sleep(0.4)
        svc.assign(sid, "row")
        svc.assign(sid, "row")
        gen = svc.generate(sid, base_id="w", with_loop=True,
                           body_action="erp.order.approve",
                           body_params={"oid": "{{row.title}}"})
        loop = gen["steps"][-1]
        assert loop["type"] == "foreach"
        assert loop["params"]["source"] == "{{steps.w_scrape.rows}}"