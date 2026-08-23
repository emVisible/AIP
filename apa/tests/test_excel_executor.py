"""Excel 执行器端到端测试（真实 xlsx 文件读写）。"""
import pytest

openpyxl = pytest.importorskip("openpyxl")

from apa_executors.excel_executor import ExcelExecutor  # noqa: E402


@pytest.fixture()
def xlsx_file(tmp_path):
    """带表头+两行数据的临时工作簿。"""
    p = tmp_path / "orders.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws.append(["order_id", "amount", "status"])
    ws.append(["A001", 120, "paid"])
    ws.append(["A002", 80, "pending"])
    wb.save(p)
    return str(p)


def _exec():
    ex = ExcelExecutor.__new__(ExcelExecutor)
    return ex


class TestReadRange:
    def test_read_with_header(self, xlsx_file):
        ok, data = _exec()._execute_action(
            "excel.read_range",
            {"file": xlsx_file, "sheet": "Orders"},
        )
        assert ok
        assert data["columns"] == ["order_id", "amount", "status"]
        assert data["rows"] == [["A001", 120, "paid"], ["A002", 80, "pending"]]
        assert data["count"] == 2

    def test_read_specific_range(self, xlsx_file):
        ok, data = _exec()._execute_action(
            "excel.read_range",
            {"file": xlsx_file, "sheet": "Orders", "range": "A1:B3"},
        )
        assert ok
        assert data["rows"][0] == ["A001", 120]

    def test_missing_file(self):
        ok, err = _exec()._execute_action(
            "excel.read_range", {"file": "/no/such.xlsx"})
        assert not ok
        assert err["code"] == "file_not_found"


class TestAppendAndWrite:
    def test_append_row(self, xlsx_file):
        ok, info = _exec()._execute_action(
            "excel.append_row",
            {"file": xlsx_file, "values": ["A003", 200, "paid"]},
        )
        assert ok
        assert info["row_index"] == 4

        _, data = _exec()._execute_action(
            "excel.read_range", {"file": xlsx_file})
        assert data["rows"][-1] == ["A003", 200, "paid"]

    def test_write_cell(self, xlsx_file):
        ok, _ = _exec()._execute_action(
            "excel.write_cell",
            {"file": xlsx_file, "cell": "C2", "value": "refunded"},
        )
        assert ok
        wb = openpyxl.load_workbook(xlsx_file)
        assert wb["Orders"]["C2"].value == "refunded"

    def test_formula_roundtrip(self, xlsx_file):
        ok, _ = _exec()._execute_action(
            "excel.set_formula",
            {"file": xlsx_file, "cell": "D1", "formula": "=SUM(B2:B3)"},
        )
        assert ok
        ok, got = _exec()._execute_action(
            "excel.get_formula", {"file": xlsx_file, "cell": "D1"})
        assert ok
        assert got["formula"] == "=SUM(B2:B3)"

    def test_formula_auto_prefix(self, xlsx_file):
        ok, out = _exec()._execute_action(
            "excel.set_formula",
            {"file": xlsx_file, "cell": "D2", "formula": "B2*2"},
        )
        assert ok and out["formula"] == "=B2*2"


class TestSheets:
    def test_list_sheets(self, xlsx_file):
        ok, data = _exec()._execute_action(
            "excel.list_sheets", {"file": xlsx_file})
        assert ok
        assert data["sheets"] == ["Orders"]
        assert data["active"] == "Orders"

    def test_add_sheet(self, xlsx_file):
        ok, _ = _exec()._execute_action(
            "excel.add_sheet", {"file": xlsx_file, "sheet": "Summary"})
        assert ok
        _, data = _exec()._execute_action(
            "excel.list_sheets", {"file": xlsx_file})
        assert "Summary" in data["sheets"]

    def test_add_duplicate_fails(self, xlsx_file):
        ok, err = _exec()._execute_action(
            "excel.add_sheet", {"file": xlsx_file, "sheet": "Orders"})
        assert not ok
        assert err["code"] == "sheet_exists"


class TestUnknownAction:
    def test_unknown(self):
        ok, err = _exec()._execute_action("excel.pivot", {})
        assert not ok
        assert err["code"] == "action_not_supported_by_executor"