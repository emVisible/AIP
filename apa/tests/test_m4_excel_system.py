"""M4 测试：Excel 高级 ×10 + 系统/文件 ×8（真实文件/进程验证）。"""
import subprocess
import sys

import pytest

from apa_executors.data_executor import DataExecutor
from apa_executors.excel_executor import ExcelExecutor


@pytest.fixture()
def xex():
    ex = ExcelExecutor.__new__(ExcelExecutor)
    return ex


@pytest.fixture()
def dex():
    ex = DataExecutor.__new__(DataExecutor)
    ex._tables = {}
    return ex


@pytest.fixture()
def styled_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    p = tmp_path / "adv.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["name", "amount"])
    ws.append(["alpha", 10])
    ws.append(["beta", 20])
    ws.append(["gamma", 30])
    ws2 = wb.create_sheet("Old")
    ws2["A1"] = "keep"
    wb.save(p)
    return str(p)


def run(ex, name, **params):
    ok, out = ex._execute_action(name, params)
    assert ok, (name, out)
    return out


class TestExcelAdvanced:
    def test_cell_style_roundtrip(self, xex, styled_xlsx):
        run(xex, "excel.set_cell_style",
            file=styled_xlsx, cell="B2", bold=True,
            font_color="FF0000", bg_color="FFFF00", font_size=14)
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.load_workbook(styled_xlsx)
        c = wb["Data"]["B2"]
        assert c.font.bold and c.font.size == 14
        assert c.fill.fill_type == "solid"

    def test_merge_cells_idempotent(self, xex, styled_xlsx):
        run(xex, "excel.merge_cells", file=styled_xlsx, range="A5:B5")
        ok2, out2 = xex._execute_action(
            "excel.merge_cells", {"file": styled_xlsx, "range": "A5:B5"})
        assert ok2 and out2["merged"] == "A5:B5"  # 重放 no-op
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.load_workbook(styled_xlsx)
        assert "A5:B5" in {str(m) for m in wb["Data"].merged_cells.ranges}

    def test_column_width(self, xex, styled_xlsx):
        o = run(xex, "excel.set_column_width",
                file=styled_xlsx, column="A", width=33)
        assert o["column"] == "A"
        o = run(xex, "excel.set_column_width",
                file=styled_xlsx, column="2", width=22)
        assert o["column"] == "B"
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.load_workbook(styled_xlsx)
        assert wb["Data"].column_dimensions["A"].width == 33
        assert wb["Data"].column_dimensions["B"].width == 22

    def test_add_chart(self, xex, styled_xlsx):
        o = run(xex, "excel.add_chart",
                file=styled_xlsx, type="bar",
                data_range="Data!A1:B4", title="销量")
        assert o["charts_on_sheet"] == 1
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.load_workbook(styled_xlsx)
        charts = wb["Data"]._charts
        assert len(charts) == 1 and charts[0].tagname == "barChart"

    def test_sheet_lifecycle(self, xex, styled_xlsx):
        run(xex, "excel.rename_sheet",
            file=styled_xlsx, old="Old", new="New")
        _, sheets = xex._execute_action("excel.list_sheets",
                                        {"file": styled_xlsx})
        assert "New" in sheets["sheets"]

        run(xex, "excel.copy_sheet",
            file=styled_xlsx, source="New", target="Backup")
        _, sheets = xex._execute_action("excel.list_sheets",
                                        {"file": styled_xlsx})
        assert "Backup" in sheets["sheets"]

        run(xex, "excel.delete_sheet", file=styled_xlsx, sheet="Backup")
        _, sheets = xex._execute_action("excel.list_sheets",
                                        {"file": styled_xlsx})
        assert "Backup" not in sheets["sheets"]

    def test_rename_to_existing_fails(self, xex, styled_xlsx):
        ok, err = xex._execute_action(
            "excel.rename_sheet",
            {"file": styled_xlsx, "old": "New", "new": "Data"})
        assert not ok and err["code"] == "sheet_exists"

    def test_find_replace(self, xex, styled_xlsx):
        o = run(xex, "excel.find_replace",
                file=styled_xlsx, find="alpha", replace="ALPHA-1")
        assert o["cells_replaced"] == 1
        _, data = xex._execute_action("excel.read_range",
                                      {"file": styled_xlsx})
        assert data["rows"][0][0] == "ALPHA-1"
        # 重放 no-op
        o2 = run(xex, "excel.find_replace",
                 file=styled_xlsx, find="alpha", replace="ALPHA-1")
        assert o2["cells_replaced"] == 0

    def test_insert_delete_row(self, xex, styled_xlsx):
        run(xex, "excel.insert_row", file=styled_xlsx,
            at=2, values=["delta", 99])
        _, data = xex._execute_action("excel.read_range",
                                      {"file": styled_xlsx})
        assert data["rows"][0] == ["delta", 99]

        run(xex, "excel.delete_row", file=styled_xlsx, at=2)
        _, data = xex._execute_action("excel.read_range",
                                      {"file": styled_xlsx})
        assert data["rows"][0] == ["alpha", 10]


class TestShellExecute:
    def test_stdout_and_exit_code(self, dex):
        if sys.platform == "win32":
            pytest.skip("posix shell 语法")
        o = run(dex, "shell.execute", cmd="echo hello-shell; exit 0")
        assert o["exit_code"] == 0 and "hello-shell" in o["stdout"]
        assert o["timed_out"] is False

    def test_nonzero_exit(self, dex):
        if sys.platform == "win32":
            pytest.skip("posix shell 语法")
        o = run(dex, "shell.execute", cmd="exit 3")
        assert o["exit_code"] == 3

    def test_timeout_kills(self, dex):
        if sys.platform == "win32":
            pytest.skip("posix sleep 语法")
        o = run(dex, "shell.execute", cmd="sleep 30",
                timeout_s=1)
        assert o["timed_out"] is True

    def test_empty_cmd(self, dex):
        ok, err = dex._execute_action("shell.execute", {"cmd": "  "})
        assert not ok and err["code"] == "missing_param"


class TestNotify:
    def test_notify_darwin_or_stdout(self, dex, monkeypatch):
        called = {}

        def fake_run(*a, **kw):
            called["args"] = a
            class R:
                returncode = 0
            return R()

        monkeypatch.setattr(subprocess, "run", fake_run)
        o = run(dex, "sys.notify", title="T", message='带"引号"')
        assert o["delivered"]
        if sys.platform == "darwin":
            script = called["args"][0][2]
            assert '\\"' in script  # 引号已转义


@pytest.mark.skipif(sys.platform != "darwin", reason="pbcopy/pbpaste")
class TestClipboard:
    def test_roundtrip(self, dex):
        marker = f"apa-clip-{id(object())}"
        run(dex, "clipboard.set", text=marker)
        got = run(dex, "clipboard.get")["text"]
        assert got == marker


class TestFileOps:
    def test_mkdir_exists_list_stat(self, dex, tmp_path):
        d = tmp_path / "nested" / "dir"
        o = run(dex, "file.mkdir", path=str(d))
        assert o["existed"] is False
        o2 = run(dex, "file.mkdir", path=str(d))
        assert o2["existed"] is True

        (d / "a.txt").write_text("12345")
        (d / "b.log").write_text("x")

        lst = run(dex, "file.list_dir", path=str(d), pattern="*.txt")
        assert lst["count"] == 1 and lst["entries"][0]["size"] == 5

        assert run(dex, "file.exists", path=str(d / "a.txt"))["exists"]
        st = run(dex, "file.stat", path=str(d / "a.txt"))
        assert st["size"] == 5 and st["is_dir"] is False

        ok, err = dex._execute_action("file.stat",
                                      {"path": str(d / "nope")})
        assert not ok and err["code"] == "file_not_found"