"""apa-executors: 数据操作执行器（对标影刀数据处理指令集）。

动作域：data.* / file.* / string.*
所有动作为纯 Python 实现，无外部依赖。
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from apa_sdk.executor_base import AIPExecutor


class DataExecutor(AIPExecutor):
    """数据操作执行器：表格/文件/字符串。"""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._tables: Dict[str, dict] = {}

    def start_observation(self) -> None:
        pass

    def _get_table(self, key: str) -> dict:
        return self._tables.get(key, {"columns": [], "rows": []})

    def _set_table(self, key: str, table: dict) -> None:
        self._tables[key] = table

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        handler_map = {
            "data.create": self._data_create,
            "data.filter": self._data_filter,
            "data.sort": self._data_sort,
            "data.to_csv": self._data_to_csv,
            "file.read_text": self._file_read_text,
            "file.write_text": self._file_write_text,
            "string.replace": self._string_replace,
            "string.split": self._string_split,
        }
        fn = handler_map.get(name)
        if fn is None:
            return False, {"code": "action_not_supported_by_executor"}
        try:
            return fn(params)
        except Exception as e:
            return False, {"code": type(e).__name__, "detail": str(e)}

    def _data_create(self, p):
        cols = p.get("columns", [])
        rows = p.get("rows", [])
        table = {"columns": cols, "rows": rows}
        self._set_table(p.get("key", "default"), table)
        return True, {"count": len(rows), "columns": cols}

    def _data_filter(self, p):
        src = self._get_table(p.get("source", ""))
        col = p["column"]
        op = p["op"]
        val = p.get("value")
        ops = {
            "==": lambda a, b: a == b,
            ">": lambda a, b: float(a or 0) > float(b or 0),
            "<": lambda a, b: float(a or 0) < float(b or 0),
            "contains": lambda a, b: str(b).lower() in str(a).lower(),
        }
        fn = ops.get(op)
        if fn is None:
            return False, {"code": f"unknown op {op}"}
        idx = src["columns"].index(col) if col in src["columns"] else -1
        filtered = [r[:] for r in src["rows"] if idx >= 0 and fn(r[idx], val)]
        result = {"columns": src["columns"], "rows": filtered, "count": len(filtered)}
        self._set_table(p.get("output_key", "filtered"), result)
        return True, result

    def _data_sort(self, p):
        src = self._get_table(p.get("source", ""))
        col = p["column"]
        reverse = p.get("reverse", False)
        try:
            idx = src["columns"].index(col)
            sorted_rows = sorted(src["rows"], key=lambda r: r[idx] or "", reverse=reverse)
        except (ValueError, IndexError):
            sorted_rows = [r[:] for r in src["rows"]]
        result = {"columns": src["columns"], "rows": sorted_rows}
        self._set_table(p.get("output_key", "sorted"), result)
        return True, result

    def _data_to_csv(self, p):
        src = self._get_table(p.get("source", ""))
        import io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(src["columns"])
        writer.writerows(src["rows"])
        return True, {"csv": buf.getvalue(), "row_count": len(src["rows"])}

    def _file_read_text(self, p):
        path = Path(p["path"])
        if not path.is_file():
            return False, {"code": "file_not_found"}
        text = path.read_text(encoding="utf-8", errors="replace")
        return True, {"text": text}

    def _file_write_text(self, p):
        path = Path(p["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(p.get("content", ""), encoding="utf-8")
        return True, {"path": str(path), "size": path.stat().st_size}

    def _string_replace(self, p):
        text = p.get("text", "")
        old = p.get("old", "")
        new = p.get("new", "")
        return True, {"result": text.replace(old, new)}

    def _string_split(self, p):
        text = p.get("text", "")
        delimiter = p.get("delimiter", ",")
        parts = text.split(delimiter)
        return True, {"parts": [p.strip() for p in parts]}