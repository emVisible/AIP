"""apa-executors: Excel 操作执行器（对标影刀 Excel 指令组）。

动作域：excel.*
依赖：openpyxl（optional-dependency: apa-core[excel]）

支持：
  excel.read_range     读取区域 → 表格数据
  excel.append_row     追加一行
  excel.write_cell     写单元格
  excel.get_formula    读公式文本
  excel.set_formula    写公式
  excel.list_sheets    列出工作表
  excel.add_sheet      新建工作表

安全：所有路径限定在进程可达文件系统；写操作先落盘临时文件再原子替换。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from apa_sdk.executor_base import AIPExecutor


def _load_openpyxl():
    try:
        import openpyxl  # noqa: PLC0415
        return openpyxl
    except ImportError as e:
        raise RuntimeError(
            "openpyxl is required for excel.* actions: "
            "uv pip install openpyxl (or pip install 'apa-core[excel]')",
        ) from e


class ExcelExecutor(AIPExecutor):
    """Excel 工作簿读写执行器。"""

    def start_observation(self) -> None:
        pass

    # ---- 内部工具 ----------------------------------------------------------

    @staticmethod
    def _wb(path: str, read_only: bool = False, data_only: bool = False):
        openpyxl = _load_openpyxl()
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"workbook not found: {path}")
        return openpyxl.load_workbook(
            str(p), read_only=read_only, data_only=data_only)

    @staticmethod
    def _atomic_save(wb, path: str) -> None:
        """临时目录写出 + 原子替换，避免写坏原文件。"""
        fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=os.path.dirname(path) or ".")
        os.close(fd)
        try:
            wb.save(tmp)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):  # save 失败时清理
                os.unlink(tmp)

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        handlers = {
            "excel.read_range": self._read_range,
            "excel.append_row": self._append_row,
            "excel.append_rows": self._append_rows,
            "excel.write_cell": self._write_cell,
            "excel.get_formula": self._get_formula,
            "excel.set_formula": self._set_formula,
            "excel.list_sheets": self._list_sheets,
            "excel.add_sheet": self._add_sheet,
            # ---- M4 Excel 高级 ----
            "excel.set_cell_style": self._set_cell_style,
            "excel.merge_cells": self._merge_cells,
            "excel.set_column_width": self._set_column_width,
            "excel.add_chart": self._add_chart,
            "excel.rename_sheet": self._rename_sheet,
            "excel.delete_sheet": self._delete_sheet,
            "excel.copy_sheet": self._copy_sheet,
            "excel.find_replace": self._find_replace,
            "excel.insert_row": self._insert_row,
            "excel.delete_row": self._delete_row,
        }
        fn = handlers.get(name)
        if fn is None:
            return False, {"code": "action_not_supported_by_executor"}
        try:
            return fn(params)
        except FileNotFoundError as e:
            return False, {"code": "file_not_found", "detail": str(e)}
        except RuntimeError as e:  # openpyxl 缺失
            return False, {"code": "dependency_missing", "detail": str(e)}
        except KeyError as e:
            return False, {"code": "missing_param", "detail": f"{e}"}
        except Exception as e:
            return False, {"code": type(e).__name__, "detail": str(e)}

    # ---- 动作实现 ----------------------------------------------------------

    def _read_range(self, p: dict) -> Tuple[bool, dict]:
        """读取 sheet!A1:D10 或整个 sheet 的已用区域。"""
        wb = self._wb(p["file"], read_only=True, data_only=True)
        try:
            ws = wb[p["sheet"]] if p.get("sheet") else wb.active
            rng = p.get("range")
            if rng:
                # 只读模式不支持切片，转换为行列边界
                from openpyxl.utils import range_boundaries
                min_col, min_row, max_col, max_row = range_boundaries(rng)
                rows_iter = ws.iter_rows(
                    min_row=min_row, max_row=max_row,
                    min_col=min_col, max_col=max_col,
                    values_only=True,
                )
            else:
                rows_iter = ws.iter_rows(values_only=True)
            header = p.get("header", True)
            rows = [list(r) for r in rows_iter]
            columns = [str(c) for c in rows[0]] if (header and rows) else []
            body = rows[1:] if (header and rows) else rows
            return True, {
                "columns": columns,
                "rows": body,
                "count": len(body),
                "sheet": ws.title,
            }
        finally:
            wb.close()

    def _append_row(self, p: dict) -> Tuple[bool, dict]:
        values = p["values"]
        wb = self._wb(p["file"])
        try:
            ws = wb[p["sheet"]] if p.get("sheet") else wb.active
            ws.append(values)
            self._atomic_save(wb, p["file"])
            return True, {
                "appended": len(values),
                "row_index": ws.max_row,
                "sheet": ws.title,
            }
        finally:
            wb.close()

    def _append_rows(self, p: dict) -> Tuple[bool, dict]:
        """批量追加多行（单次落盘，万行级吞吐）。"""
        rows = p["rows"]
        wb = self._wb(p["file"])
        try:
            ws = wb[p["sheet"]] if p.get("sheet") else wb.active
            for r in rows:
                ws.append(r)
            self._atomic_save(wb, p["file"])
            return True, {
                "appended": len(rows),
                "row_index": ws.max_row,
                "sheet": ws.title,
            }
        finally:
            wb.close()

    def _write_cell(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"])
        try:
            ws = wb[p["sheet"]] if p.get("sheet") else wb.active
            ws[p["cell"]] = p["value"]
            self._atomic_save(wb, p["file"])
            return True, {"cell": p["cell"], "value": p["value"]}
        finally:
            wb.close()

    def _get_formula(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"], data_only=False)
        try:
            ws = wb[p["sheet"]] if p.get("sheet") else wb.active
            return True, {"cell": p["cell"], "formula": ws[p["cell"]].value}
        finally:
            wb.close()

    def _set_formula(self, p: dict) -> Tuple[bool, dict]:
        formula: str = p["formula"]
        if not formula.startswith("="):
            formula = f"={formula}"
        wb = self._wb(p["file"])
        try:
            ws = wb[p["sheet"]] if p.get("sheet") else wb.active
            ws[p["cell"]] = formula
            self._atomic_save(wb, p["file"])
            return True, {"cell": p["cell"], "formula": formula}
        finally:
            wb.close()

    def _list_sheets(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"], read_only=True)
        try:
            names = list(wb.sheetnames)
            return True, {"sheets": names, "active": wb.active.title}
        finally:
            wb.close()

    def _add_sheet(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"])
        try:
            if p["sheet"] in wb.sheetnames:
                return False, {"code": "sheet_exists", "sheet": p["sheet"]}
            idx: Optional[int] = p.get("index")
            ws = wb.create_sheet(p["sheet"], index=idx)
            self._atomic_save(wb, p["file"])
            return True, {"sheet": ws.title, "position": (
                wb.index(ws) if idx is not None else None)}
        finally:
            wb.close()

    # ==== M4 Excel 高级 =====================================================

    @staticmethod
    def _ws(wb, p: dict):
        return wb[p["sheet"]] if p.get("sheet") else wb.active

    def _set_cell_style(self, p: dict) -> Tuple[bool, dict]:
        """单元格样式：bold / font_size / font_color / bg_color（RRGGBB）。"""
        from openpyxl.styles import Font, PatternFill

        wb = self._wb(p["file"])
        try:
            ws = self._ws(wb, p)
            cell = ws[p["cell"]]
            font = cell.font.copy(
                bold=bool(p.get("bold", cell.font.bold)),
                size=p.get("font_size", cell.font.size),
                color=(p["font_color"].upper()
                       if p.get("font_color") else cell.font.color),
            )
            cell.font = font
            if p.get("bg_color"):
                cell.fill = PatternFill(
                    start_color=p["bg_color"].upper(),
                    end_color=p["bg_color"].upper(),
                    fill_type="solid")
            self._atomic_save(wb, p["file"])
            return True, {"cell": p["cell"]}
        finally:
            wb.close()

    def _merge_cells(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"])
        try:
            ws = self._ws(wb, p)
            rng: str = p["range"]
            existing = {str(m) for m in ws.merged_cells.ranges}
            if rng not in existing:  # 重放幂等
                ws.merge_cells(rng)
                self._atomic_save(wb, p["file"])
            return True, {"merged": rng}
        finally:
            wb.close()

    def _set_column_width(self, p: dict) -> Tuple[bool, dict]:
        from openpyxl.utils import get_column_letter

        wb = self._wb(p["file"])
        try:
            ws = self._ws(wb, p)
            col = str(p.get("column", "A"))
            letter = (get_column_letter(int(col))
                      if col.isdigit() else col.upper())
            ws.column_dimensions[letter].width = float(p.get("width", 10))
            self._atomic_save(wb, p["file"])
            return True, {"column": letter,
                          "width": float(p.get("width", 10))}
        finally:
            wb.close()

    def _add_chart(self, p: dict) -> Tuple[bool, dict]:
        """柱状/折线图。data_range 形如 "Sheet!B2:C5" 或当前表 "B2:C5"。"""
        from openpyxl.chart import BarChart, LineChart, Reference

        wb = self._wb(p["file"])
        try:
            ws = self._ws(wb, p)
            chart_type = p.get("type", "bar")
            if chart_type == "line":
                ch = LineChart()
            elif chart_type == "bar":
                ch = BarChart()
            else:
                return False, {"code": f"unknown chart type {chart_type!r}"}

            data_range: str = p["data_range"]
            sheet_part = None
            if "!" in data_range:
                sheet_part, _, cells = data_range.partition("!")
                ref_ws = wb[sheet_part]
            else:
                cells = data_range
                ref_ws = ws
            data = Reference(ref_ws, range_string=(
                f"{sheet_part}!{cells}" if sheet_part else cells))
            ch.add_data(data, titles_from_data=bool(p.get("titles_from_data",
                                                         False)))
            ch.title = p.get("title") or None
            anchor = p.get("anchor", "E2")
            ws.add_chart(ch, anchor)
            self._atomic_save(wb, p["file"])
            return True, {"chart_type": chart_type, "anchor": anchor,
                          "charts_on_sheet": len(ws._charts)}
        finally:
            wb.close()

    def _rename_sheet(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"])
        try:
            old, new = p["old"], p["new"]
            if new in wb.sheetnames and new != old:
                return False, {"code": "sheet_exists", "sheet": new}
            if old not in wb.sheetnames:
                return False, {"code": "sheet_not_found", "sheet": old}
            wb[old].title = new
            self._atomic_save(wb, p["file"])
            return True, {"renamed": [old, new]}
        finally:
            wb.close()

    def _delete_sheet(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"])
        try:
            name = p["sheet"]
            if name not in wb.sheetnames:
                return False, {"code": "sheet_not_found", "sheet": name}
            if len(wb.sheetnames) == 1:
                return False, {"code": "last_sheet"}
            del wb[name]
            self._atomic_save(wb, p["file"])
            return True, {"deleted": name,
                          "remaining": len(wb.sheetnames)}
        finally:
            wb.close()

    def _copy_sheet(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"])
        try:
            src, target = p["source"], p["target"]
            if src not in wb.sheetnames:
                return False, {"code": "sheet_not_found", "sheet": src}
            if target in wb.sheetnames:
                return False, {"code": "sheet_exists", "sheet": target}
            src_ws = wb[src]
            tgt_ws = wb.create_sheet(target)
            for row in src_ws.iter_rows():
                for c in row:
                    tgt_ws[c.coordinate].value = c.value
            self._atomic_save(wb, p["file"])
            return True, {"copied": [src, target]}
        finally:
            wb.close()

    def _find_replace(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"])
        try:
            ws = self._ws(wb, p)
            find: str = p["find"]
            repl: str = p.get("replace", "")
            n = 0
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and find in c.value:
                        c.value = c.value.replace(find, repl)
                        n += 1
            if n:
                self._atomic_save(wb, p["file"])
            return True, {"cells_replaced": n}
        finally:
            wb.close()

    def _insert_row(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"])
        try:
            ws = self._ws(wb, p)
            at = int(p["at"])
            ws.insert_rows(at)
            values = p.get("values")
            if values:
                for j, v in enumerate(values, start=1):
                    ws.cell(row=at, column=j, value=v)
            self._atomic_save(wb, p["file"])
            return True, {"inserted_at": at}
        finally:
            wb.close()

    def _delete_row(self, p: dict) -> Tuple[bool, dict]:
        wb = self._wb(p["file"])
        try:
            ws = self._ws(wb, p)
            at = int(p["at"])
            ws.delete_rows(at)
            self._atomic_save(wb, p["file"])
            return True, {"deleted_at": at}
        finally:
            wb.close()
