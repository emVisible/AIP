"""数据抓取向导纯函数层测试（无浏览器依赖）。"""
from apa_core.scrape import (
    build_scrape_steps,
    common_prefix_len,
    infer_row_selector,
    relative_column_path,
)


def seg(tag, idx, cls="", _id=""):
    return {"tag": tag, "idx": idx, "cls": cls, "id": _id}


# 典型 HTML 表格：html>body>table>tbody>tr
TABLE_ROW = [
    seg("html", 0), seg("body", 0), seg("table", 0), seg("tbody", 0),
]
ROW1 = TABLE_ROW + [seg("tr", 0)]
ROW2 = TABLE_ROW + [seg("tr", 1)]

# div 列表：div.list > div.item.item-x
LIST_HEAD = [
    seg("html", 0), seg("body", 0), seg("div", 0, "list"),
]
ITEM1 = LIST_HEAD + [seg("div", 0, "item")]
ITEM2 = LIST_HEAD + [seg("div", 1, "item")]


class TestCommonPrefix:
    def test_table_rows_share_tbody(self):
        assert common_prefix_len(ROW1, ROW2) == len(TABLE_ROW)

    def test_disjoint_paths(self):
        a = [seg("html", 0), seg("div", 0)]
        b = [seg("html", 0), seg("span", 0)]
        assert common_prefix_len(a, b) == 1

    def test_identical(self):
        assert common_prefix_len(ROW1, ROW1) == len(ROW1)


class TestInferRowSelector:
    def test_shared_class_strategy(self):
        r = infer_row_selector(
            ITEM1, ITEM2,
            ctx={"repeat_parent": {"same_tag_siblings": {"div": 5}}})
        assert r["ok"] and r["strategy"] == "shared_class"
        assert r["selector"] == "div.list > div.item"

    def test_bare_tag_for_table(self):
        # tr 无类 → 裸标签策略
        r = infer_row_selector(
            ROW1, ROW2,
            ctx={"repeat_parent": {"same_tag_siblings": {"tr": 8}}})
        assert r["ok"] and r["strategy"] == "bare_tag"
        assert r["selector"].endswith("> tr")

    def test_nth_fallback_when_single_sibling(self):
        r = infer_row_selector(
            ROW1, ROW2,
            ctx={"repeat_parent": {"same_tag_siblings": {"tr": 1}}})
        assert r["ok"] and r["strategy"] == "nth_fallback"
        assert ":nth-of-type(1)" in r["selector"]

    def test_reject_same_element(self):
        r = infer_row_selector(ROW1, ROW1)
        assert not r["ok"] and r["reason"] == "nested/same element"

    def test_reject_no_common(self):
        a = [seg("html", 0), seg("div", 0)]
        b = [seg("html", 1), seg("div", 0)]  # 不同 html? 构造无前缀
        r = infer_row_selector([seg("iframe", 0)], [seg("frame", 0)])
        assert not r["ok"]

    def test_different_tags_at_axis(self):
        p1 = LIST_HEAD + [seg("p", 0)]
        p2 = LIST_HEAD + [seg("li", 0)]
        r = infer_row_selector(p1, p2)
        assert not r["ok"]
        assert r["reason"] == "different tags at repeat axis"


class TestRelativeColumnPath:
    ROW = ROW1

    def test_direct_cell(self):
        col = ROW1 + [seg("td", 0)]
        r = relative_column_path(ROW1, col)
        assert r["ok"] and r["selector"] == "td:nth-of-type(1)"

    def test_nested_cell(self):
        col = ROW1 + [seg("td", 2), seg("span", 0, "price")]
        r = relative_column_path(ROW1, col)
        assert r["ok"]
        assert r["selector"] == "td:nth-of-type(3) > span.price:nth-of-type(1)"

    def test_row_itself_is_direct(self):
        r = relative_column_path(ROW1, ROW1)
        assert r["ok"] and r["direct"] and r["selector"] == "."

    def test_column_outside_row_fails(self):
        outside = TABLE_ROW[:2] + [seg("footer", 0), seg("a", 0)]
        r = relative_column_path(ROW1, outside)
        assert not r["ok"]

    def test_item_list_nested(self):
        col = ITEM1 + [seg("h3", 0)]
        r = relative_column_path(ITEM1, col)
        assert r["ok"] and r["selector"] == "h3:nth-of-type(1)"


class TestBuildSteps:
    def test_basic_steps(self):
        steps = build_scrape_steps(
            process_step_base="scrape",
            url="https://x.com/list",
            row_selector="table > tbody > tr",
            columns={"name": "td:nth-of-type(1)",
                     "amount": "td:nth-of-type(3)"},
        )
        ids = [s["id"] for s in steps]
        assert ids == ["scrape_open", "scrape_scrape"]
        sc = steps[1]["params"]
        assert sc["row_selector"] == "table > tbody > tr"
        assert sc["columns"]["amount"] == "td:nth-of-type(3)"
        assert sc["output_context"] == "scrape_data"

    def test_with_pagination_and_loop(self):
        steps = build_scrape_steps(
            process_step_base="w",
            url="u",
            row_selector="div.item",
            columns={"t": "h3"},
            next_selector="a.next",
            body_action="erp.order.approve",
            body_params={"oid": "{{row.id}}"},
        )
        ids = [s["id"] for s in steps]
        assert ids == ["w_open", "w_scrape", "w_next_hint", "w_loop"]
        loop = steps[-1]
        assert loop["type"] == "foreach"
        assert loop["params"]["source"] == "{{steps.w_scrape.rows}}"
        assert loop["params"]["body_action"] == "erp.order.approve"

    def test_filter_step(self):
        steps = build_scrape_steps(
            process_step_base="s",
            url="u",
            row_selector="tr",
            columns={},
            filter_column="amount",
            filter_value=100,
        )
        f = steps[-1]
        assert f["action"] == "data.filter"
        assert f["params"]["value"] == 100