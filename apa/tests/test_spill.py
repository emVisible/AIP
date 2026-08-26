"""H1 §4.3 spill 中间件测试（docs/harness-fusion.md 验收标准）。"""
import json

import pytest

from apa_core.spill import SpillCorrupt, SpillStore


@pytest.fixture()
def store(tmp_path):
    return SpillStore(tmp_path / "spills", threshold=1000)


def _big_rows(n=200):
    return {"columns": ["a", "b"],
            "rows": [{"a": f"v{i}", "b": i} for i in range(n)],
            "count": n}


def test_small_result_passthrough_untouched(store):
    small = {"rows": [{"a": 1}], "count": 1}
    out, spilled = store.maybe_spill("browser.extract_table", small)
    assert out is small and spilled is False


def test_whitelist_gate(store):
    big = json.dumps(_big_rows())
    # 非白名单动作：超阈值也不 spill
    out, spilled = store.maybe_spill("string.upper", big)
    assert spilled is False and out is big
    # 白名单动作：触发
    out, spilled = store.maybe_spill("browser.extract_table", _big_rows())
    assert spilled is True and out["__spill__"] is True
    assert out["truncated"] is True
    assert len(out["preview"]) <= 2000


def test_spill_roundtrip_and_corruption(store):
    ref_obj, spilled = store.maybe_spill("file.read_csv", _big_rows(300))
    assert spilled
    original = store.read_spill(ref_obj["spill_ref"])
    assert original["count"] == 300

    # 损坏 → 明确报错而非静默空值
    path = store._dir / f"{ref_obj['spill_ref']}.json"
    path.write_text("{broken")
    with pytest.raises(SpillCorrupt, match="损坏"):
        store.read_spill(ref_obj["spill_ref"])

    # 缺失 → 明确报错
    path.unlink()
    with pytest.raises(SpillCorrupt, match="不存在"):
        store.read_spill(ref_obj["spill_ref"])


def test_illegal_ref_rejected(store):
    with pytest.raises(SpillCorrupt, match="illegal"):
        store.read_spill("../escape")


def test_unserializable_result_falls_back(store):
    class Weird:
        pass
    out, spilled = store.maybe_spill("browser.extract_table", Weird())
    assert spilled is False  # 不可序列化：放弃 spill，原样返回
