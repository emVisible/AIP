"""APA 数据处理吞吐基准。

覆盖三条典型 RPA 重负载路径：
  1. DataExecutor 表格管道：create → filter → sort → to_csv（10k 行）
  2. ProcessEngine foreach：1k 次子流程循环
  3. ExcelExecutor：10k 行追加 + 全量回读

    python -m benchmarks.data_throughput
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

APA_ROOT = Path(__file__).resolve().parent.parent
for p in ("apa-core", "apa-sdk-python", "apa-executors"):
    sys.path.insert(0, str(APA_ROOT / "packages" / p))

from apa_core.process import ProcessEngine, build_process  # noqa: E402


def _mk_rows(n: int) -> list[list]:
    return [[f"ORD-{i:06d}", i % 97, (i * 7) % 1000, "paid"] for i in range(n)]


def bench_data_pipeline(n_rows: int) -> dict:
    from apa_executors.data_executor import DataExecutor

    ex = DataExecutor.__new__(DataExecutor)
    ex._tables = {}

    t0 = time.perf_counter()
    ex._execute_action("data.create", {
        "key": "t", "columns": ["id", "sku", "amount", "status"],
        "rows": _mk_rows(n_rows)})
    t_create = time.perf_counter() - t0

    t0 = time.perf_counter()
    ex._execute_action("data.filter", {
        "source": "t", "column": "amount", "op": ">", "value": 500,
        "output_key": "big"})
    t_filter = time.perf_counter() - t0

    t0 = time.perf_counter()
    ex._execute_action("data.sort", {
        "source": "big", "column": "amount", "reverse": True,
        "output_key": "sorted"})
    t_sort = time.perf_counter() - t0

    t0 = time.perf_counter()
    ok, out = ex._execute_action("data.to_csv", {"source": "sorted"})
    t_csv = time.perf_counter() - t0

    assert ok and out["row_count"] > 0
    return {"rows_in": n_rows, "create_s": t_create, "filter_s": t_filter,
            "sort_s": t_sort, "to_csv_s": t_csv,
            "total_s": t_create + t_filter + t_sort + t_csv}


def bench_foreach(n_items: int) -> dict:
    sent_log: list = []

    def send_fn(action, params):
        sent_log.append((action, params))
        return True, {"ok": True}

    steps_spec = [{
        "id": "loop", "type": "foreach",
        "params": {
            "source": json.dumps(
                [{"order_id": f"O{i}"} for i in range(n_items)]),
            "item_var": "row",
            "body_action": "erp.order.approve",
            "body_params": {"oid": "{{row.order_id}}"},
        },
    }]
    proc = build_process({"process": {
        "id": "bench_foreach", "mode": "process",
        "trigger": {"type": "manual"},
        "max_actions": n_items * 2 + 10,
        "steps": steps_spec,
    }})
    eng = ProcessEngine(proc, send_fn)
    eng.run.scopes["event"] = {}

    t0 = time.perf_counter()
    eng._run_from(0)
    dt = time.perf_counter() - t0

    assert eng.run.outcome == "success"
    assert len(sent_log) == n_items
    return {"items": n_items, "total_s": dt, "per_item_ms": dt / n_items * 1000}


def bench_excel(n_rows: int) -> dict:
    openpyxl = __import__("openpyxl")
    from apa_executors.excel_executor import ExcelExecutor

    ex = ExcelExecutor.__new__(ExcelExecutor)
    tmp = Path(tempfile.mkdtemp()) / "bench.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bench"
    ws.append(["id", "sku", "amount", "status"])
    wb.save(tmp)

    t0 = time.perf_counter()
    batch = 500
    appended = 0
    for off in range(0, n_rows, batch):
        ok, info = ex._execute_action("excel.append_rows", {
            "file": str(tmp),
            "rows": _mk_rows(batch)[:batch],
        })
        assert ok
        appended += info["appended"]
    t_append = time.perf_counter() - t0

    t0 = time.perf_counter()
    ok, out = ex._execute_action("excel.read_range",
                                 {"file": str(tmp), "sheet": "Bench"})
    t_read = time.perf_counter() - t0

    assert ok and out["count"] == n_rows, \
        f"readback {out.get('count')} != {n_rows}"
    return {"rows_target": n_rows, "rows_appended": appended,
            "append_s": t_append, "read_s": t_read, "read_rows": out["count"]}


def main() -> int:
    ap = argparse.ArgumentParser(prog="benchmarks.data_throughput")
    ap.add_argument("--rows", type=int, default=10_000)
    ap.add_argument("--foreach-items", type=int, default=1_000)
    args = ap.parse_args()

    report = {
        "data_pipeline": bench_data_pipeline(args.rows),
        "foreach_loop": bench_foreach(args.foreach_items),
        "excel_io": bench_excel(args.rows),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # 冒烟阈值（CI 防回归）：宽松上限，防数量级退化
    dp = report["data_pipeline"]
    fe = report["foreach_loop"]
    assert dp["total_s"] < 30, f"data pipeline too slow: {dp['total_s']:.1f}s"
    assert fe["per_item_ms"] < 50, \
        f"foreach too slow per item: {fe['per_item_ms']:.1f}ms"

    print("\n✅ data throughput benchmark passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())