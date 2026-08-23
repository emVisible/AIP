"""数据吞吐冒烟基准（CI 防数量级退化；阈值宽松）。"""
import sys
from pathlib import Path

APA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APA_ROOT / "benchmarks"))
for _p in ("apa-core", "apa-sdk-python", "apa-executors"):
    sys.path.insert(0, str(APA_ROOT / "packages" / _p))

import data_throughput as dt  # noqa: E402


class TestDataThroughputSmoke:
    def test_pipeline_small(self):
        r = dt.bench_data_pipeline(2_000)
        assert r["total_s"] < 5
        # 过滤后应有约一半行（amount>500 占比 ~49.5%）
        assert r["filter_s"] < r["total_s"]

    def test_foreach_small(self):
        r = dt.bench_foreach(200)
        assert r["per_item_ms"] < 50

    def test_excel_roundtrip(self, tmp_path, monkeypatch):
        openpyxl = __import__("openpyxl")
        from apa_executors.excel_executor import ExcelExecutor

        xlsx = tmp_path / "smoke.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Bench"
        ws.append(["id", "sku", "amount", "status"])
        wb.save(xlsx)

        ex = ExcelExecutor.__new__(ExcelExecutor)
        ok, info = ex._execute_action("excel.append_rows", {
            "file": str(xlsx),
            "rows": dt._mk_rows(1_000),
        })
        assert ok and info["appended"] == 1_000

        ok, out = ex._execute_action("excel.read_range",
                                     {"file": str(xlsx), "sheet": "Bench"})
        assert ok and out["count"] == 1_000