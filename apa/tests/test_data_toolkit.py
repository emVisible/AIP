"""M1 数据工具包全量单测（28 个新动作）。"""
import pytest

from apa_executors.data_executor import DataExecutor


@pytest.fixture()
def ex():
    ex = DataExecutor.__new__(DataExecutor)
    ex._tables = {}
    return ex


def run(ex, name, **params):
    ok, out = ex._execute_action(name, params)
    assert ok, (name, out)
    return out


class TestStringToolkit:
    def test_regex_extract_all_and_first(self, ex):
        o = run(ex, "string.regex_extract",
                text="a1b22c333", pattern=r"\d+")
        assert o["matches"] == ["1", "22", "333"] and o["first"] == "1"

    def test_regex_extract_group(self, ex):
        o = run(ex, "string.regex_extract",
                text="2026-08-23", pattern=r"(\d{4})-(\d{2})-(\d{2})",
                group=2)
        assert o["first"] == "08"

    def test_regex_ignore_case(self, ex):
        o = run(ex, "string.regex_test", text="HELLO", pattern=r"^hello")
        assert o["matched"] is False
        o = run(ex, "string.regex_extract", text="HELLO", pattern=r"h",
                ignore_case=True)
        assert o["count"] == 1

    def test_regex_replace(self, ex):
        o = run(ex, "string.regex_replace", text="a1b2", pattern=r"\d",
                repl="#")
        assert o["result"] == "a#b#"

    def test_regex_test(self, ex):
        assert run(ex, "string.regex_test", text="abc", pattern=r"^a")["matched"]
        assert not run(ex, "string.regex_test", text="abc",
                       pattern=r"^z")["matched"]

    def test_trim_upper_lower(self, ex):
        assert run(ex, "string.trim", text="  x\n")["result"] == "x"
        assert run(ex, "string.upper", text="ab")["result"] == "AB"
        assert run(ex, "string.lower", text="Ab")["result"] == "ab"

    def test_format_template_missing_var_kept(self, ex):
        o = run(ex, "string.format_template",
                template="{greet} {name}!", vars={"name": "李雷"})
        assert o["result"] == "{greet} 李雷!"

    def test_pad_aligns(self, ex):
        assert run(ex, "string.pad", text="7", width=3,
                   fillchar="0", align="left")["result"] == "007"
        assert run(ex, "string.pad", text="7", width=3,
                   align="right")["result"] == "7  "
        assert run(ex, "string.pad", text="7", width=5,
                   fillchar="*", align="center")["result"] == "**7**"

    def test_starts_with_contains(self, ex):
        assert run(ex, "string.starts_with", text="hello",
                   prefix="he")["matched"]
        assert run(ex, "string.contains", text="Hello", needle="ELL",
                   ignore_case=True)["matched"]
        assert not run(ex, "string.contains", text="Hello",
                       needle="ELL")["matched"]

    def test_regex_bad_pattern_reported(self, ex):
        ok, err = ex._execute_action("string.regex_test",
                                     {"text": "x", "pattern": "("})
        assert not ok and err["code"] in ("error", "re.error")


class TestEncode:
    def test_base64_roundtrip_utf8(self, ex):
        enc = run(ex, "encode.base64_encode", text="中文 abc")
        dec = run(ex, "encode.base64_decode", b64=enc["result"])
        assert dec["result"] == "中文 abc"

    def test_url_roundtrip(self, ex):
        enc = run(ex, "encode.url_encode", text="a b/c?d=中")
        assert "/" not in enc["result"].replace("https", "")
        dec = run(ex, "encode.url_decode", text=enc["result"])
        assert dec["result"] == "a b/c?d=中"


class TestJson:
    def test_parse_stringify_roundtrip(self, ex):
        s = run(ex, "json.stringify", value={"k": [1, "中"], "n": None})["text"]
        v = run(ex, "json.parse", text=s)["value"]
        assert v == {"k": [1, "中"], "n": None}

    def test_stringify_indent_and_default_str(self, ex):
        o = run(ex, "json.stringify", value={"d": {1, 2}}, indent=2)
        assert "\n" in o["text"]


class TestDatetime:
    def test_now_formats(self, ex):
        o = run(ex, "dt.now", fmt="%Y/%m/%d")
        assert len(o["formatted"]) == 10 and o["epoch"] > 1e9

    def test_parse_custom_fmt(self, ex):
        o = run(ex, "dt.parse", text="2026/08/23 10:30", fmt="%Y/%m/%d %H:%M")
        assert o["iso"].startswith("2026-08-23T10:30")

    def test_add_days_hours(self, ex):
        base = run(ex, "dt.parse", text="2026-01-01T00:00:00")["iso"]
        o = run(ex, "dt.add", iso=base, days=1, hours=2, minutes=3,
                seconds=4)
        assert o["iso"] == "2026-01-02T02:03:04"

    def test_diff_units(self, ex):
        a = "2026-01-01T00:00:00"
        b = "2026-01-02T12:00:00"
        assert run(ex, "dt.diff", a=a, b=b)["value"] == 36 * 3600
        assert run(ex, "dt.diff", a=a, b=b, unit="hours")["value"] == 36
        assert run(ex, "dt.diff", a=a, b=b, unit="days")["value"] == 1.5

    def test_timestamp(self, ex):
        o = run(ex, "dt.timestamp", iso="1970-01-02T00:00:00")
        assert o["epoch"] == 86400.0


class TestHashUuid:
    def test_md5_known_vector(self, ex):
        assert run(ex, "hash.md5", text="abc")["digest"] == \
            "900150983cd24fb0d6963f7d28e17f72"

    def test_sha256_known_vector(self, ex):
        d = run(ex, "hash.sha256", text="abc")["digest"]
        assert d.startswith("ba7816bf") and len(d) == 64

    def test_uuid_shape(self, ex):
        u = run(ex, "uuid.gen")["uuid"]
        assert u.count("-") == 4 and len(u) == 36


class TestDataEnhance:
    @pytest.fixture()
    def table(self, ex):
        run(ex, "data.create",
            key="t", columns=["name", "dept", "salary"],
            rows=[
                ["张三", "A", 100],
                ["李四", "B", 200],
                ["王五", "A", 300],
                ["张三", "C", 50],   # 重名用于 distinct
            ])
        return ex

    def test_aggregate_funcs(self, table):
        g = lambda func: run(table, "data.aggregate", source="t",
                             column="salary", func=func)["value"]
        assert g("sum") == 650
        assert g("avg") == 162.5
        assert g("min") == 50
        assert g("max") == 300
        assert g("count") == 4

    def test_distinct_by_name(self, table):
        o = run(table, "data.distinct", source="t", column="name")
        assert o["count"] == 3          # 张三去重
        assert [r[0] for r in o["rows"]] == ["张三", "李四", "王五"]

    def test_slice(self, table):
        o = run(table, "data.slice", source="t", start=1, stop=3)
        assert o["count"] == 2
        assert o["rows"][0][0] == "李四"

    def test_json_to_table(self, ex):
        o = run(ex, "data.json_to_table",
                items=[{"a": 1, "b": 2}, {"a": 3, "c": 4}], key="j")
        assert o["columns"] == ["a", "b", "c"]     # 键并集保序
        assert o["rows"][1] == [3, None, 4]
        # 与 aggregate 联动
        assert run(ex, "data.aggregate", source="j",
                   column="a", func="sum")["value"] == 4