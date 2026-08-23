"""apa-core: DataTable —— 内存表格数据操作（对标影刀/UiPath DataTable）。

RPA 核心中间件：步骤之间传递结构化表格数据。
支持 CSV/JSON 序列化、过滤、排序、聚合。

用法（ProcessEngine 步骤中通过 data.* 动作调用）：
    data.create columns=[name,amount] rows=[[Alice,100],[Bob,200]] → table
    data.filter source=table column=amount op=">" value=50 → filtered
    data.to_csv source=filtered path=/tmp/output.csv
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional


class DataTable:
    """内存表格：列定义 + 行数据。"""

    __slots__ = ("columns", "rows")

    def __init__(self, columns: Optional[List[str]] = None,
                 rows: Optional[List[List[Any]]] = None) -> None:
        self.columns: List[str] = columns or []
        self.rows: List[List[Any]] = rows or []

    @classmethod
    def from_dicts(cls, items: List[Dict[str, Any]]) -> "DataTable":
        if not items:
            return cls()
        cols = list(items[0].keys())
        return cls(columns=cols, rows=[[item.get(c) for c in cols] for item in items])

    def to_dicts(self) -> List[Dict[str, Any]]:
        return [dict(zip(self.columns, row)) for row in self.rows]

    def add_row(self, *values: Any) -> None:
        self.rows.append(list(values))

    def filter(self, column: str, op: str, value: Any) -> "DataTable":
        col_idx = self.columns.index(column) if column in self.columns else -1
        if col_idx < 0:
            return DataTable(columns=self.columns[:])
        ops = {
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            "contains": lambda a, b: str(b) in str(a),
            "startswith": lambda a, b: str(a).startswith(str(b)),
        }
        fn = ops.get(op)
        if fn is None:
            return DataTable(columns=self.columns[:], rows=[r[:] for r in self.rows])
        return DataTable(
            columns=self.columns[:],
            rows=[r[:] for r in self.rows if fn(r[col_idx], value)],
        )

    def sort(self, column: str, *, reverse: bool = False) -> "DataTable":
        try:
            idx = self.columns.index(column)
        except ValueError:
            return DataTable(columns=self.columns[:], rows=[r[:] for r in self.rows])
        sorted_rows = sorted(self.rows, key=lambda r: r[idx], reverse=reverse)
        return DataTable(columns=self.columns[:], rows=sorted_rows)

    def to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(self.columns)
        writer.writerows(self.rows)
        return buf.getvalue()

    @classmethod
    def from_csv(cls, text: str) -> "DataTable":
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return cls()
        return cls(columns=rows[0], rows=rows[1:])

    def to_json(self) -> str:
        return json.dumps(self.to_dicts(), ensure_ascii=False)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def summary(self) -> Dict[str, Any]:
        return {"columns": self.columns, "row_count": self.row_count}