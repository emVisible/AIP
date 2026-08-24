"""P24-M1 列表/字典操作测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))

import pytest

from apa_executors.data_executor import DataExecutor  # noqa: E402


@pytest.fixture()
def ex():
    ex = DataExecutor.__new__(DataExecutor)
    ex._tables = {}
    ex._lists = {}
    ex._dicts = {}
    return ex


def run(ex, name, **params):
    ok, out = ex._execute_action(name, params)
    assert ok, (name, out)
    return out


class TestListOps:
    def test_create_and_append(self, ex):
        run(ex, "list.create", key="todo", items=[1])
        run(ex, "list.append", key="todo", item=2)
        run(ex, "list.append", key="todo", item=3)
        assert run(ex, "list.length", key="todo")["count"] == 3

    def test_insert_at_index(self, ex):
        run(ex, "list.create", key="l", items=["a", "c"])
        run(ex, "list.insert", key="l", index=1, item="b")
        assert run(ex, "list.get", key="l", index=1)["value"] == "b"

    def test_remove_at(self, ex):
        run(ex, "list.create", key="l", items=[1, 2, 3])
        o = run(ex, "list.remove_at", key="l", index=1)
        assert o["removed"] == 2
        assert run(ex, "list.length", key="l")["count"] == 2

    def test_remove_value_not_found(self, ex):
        run(ex, "list.create", key="l", items=[1])
        ok, err = ex._execute_action("list.remove_value",
                                     {"key": "l", "value": 99})
        assert not ok and err["code"] == "value_not_found"

    def test_get_out_of_range(self, ex):
        run(ex, "list.create", key="l", items=[])
        ok, err = ex._execute_action("list.get",
                                     {"key": "l", "index": 5})
        assert not ok and err["code"] == "index_out_of_range"

    def test_set_overwrites(self, ex):
        run(ex, "list.create", key="l", items=[1, 2])
        run(ex, "list.set", key="l", index=0, item="new")
        assert run(ex, "list.get", key="l", index=0)["value"] == "new"

    def test_reverse(self, ex):
        run(ex, "list.create", key="r", items=[1, 2, 3])
        run(ex, "list.reverse", key="r")
        lst = ex._lists["r"]
        assert lst == [3, 2, 1]

    def test_sort_ascending(self, ex):
        run(ex, "list.create", key="s", items=[3, 1, 2])
        run(ex, "list.sort", key="s")
        assert ex._lists["s"] == [1, 2, 3]

    def test_sort_descending(self, ex):
        run(ex, "list.create", key="s", items=[1, 3, 2])
        run(ex, "list.sort", key="s", reverse=True)
        assert ex._lists["s"] == [3, 2, 1]

    def test_sort_by_dict_key(self, ex):
        run(ex, "list.create", key="d", items=[
            {"name": "b", "v": 2}, {"name": "a", "v": 1}])
        run(ex, "list.sort", key="d", sort_key="name")
        names = [x["name"] for x in ex._lists["d"]]
        assert names == ["a", "b"]


class TestDictOps:
    def test_create_set_get(self, ex):
        run(ex, "dict.create", key="cfg")
        run(ex, "dict.set", key="cfg", k="host", v="localhost")
        o = run(ex, "dict.get", key="cfg", k="host")
        assert o["value"] == "localhost"

    def test_get_default_when_missing(self, ex):
        o = run(ex, "dict.get", key="empty_d", k="nope", default="fallback")
        assert o["value"] == "fallback"

    def test_has_key(self, ex):
        run(ex, "dict.set", key="d2", k="exists", v=1)
        assert run(ex, "dict.has_key", key="d2", k="exists")["exists"]
        assert not run(ex, "dict.has_key", key="d2", k="nope")["exists"]

    def test_keys_values(self, ex):
        run(ex, "dict.set", key="kv", k="a", v=1)
        run(ex, "dict.set", key="kv", k="b", v=2)
        keys = run(ex, "dict.keys", key="kv")["keys"]
        vals = run(ex, "dict.values", key="kv")["values"]
        assert set(keys) == {"a", "b"}
        assert sorted(vals) == [1, 2]

    def test_remove(self, ex):
        run(ex, "dict.set", key="rm", k="temp", v=1)
        ok, out = ex._execute_action("dict.remove",
                                     {"key": "rm", "k": "temp"})
        assert ok
        ok2, _ = ex._execute_action("dict.remove",
                                     {"key": "rm", "k": "temp"})
        assert not ok2

    def test_chained_with_foreach_source(self, ex):
        """字典 values 可作为 foreach source。"""
        run(ex, "dict.set", key="prices", k="A", v=100)
        run(ex, "dict.set", key="prices", k="B", v=200)
        vals = run(ex, "dict.values", key="prices")["values"]
        assert sum(vals) == 300