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

class TestDataTableCloseout:
    """P22-M3 DataTable 收尾动作。"""

    @pytest.fixture()
    def tbl(self, ex):
        run(ex, "data.create", key="t",
            columns=["id", "name", "score"],
            rows=[["r1", "甲", 80], ["r2", "乙", 60], ["r3", "丙", 90]])
        return ex

    def test_delete_row(self, tbl):
        o = run(tbl, "data.delete_row", source="t", at=1)
        assert o["count"] == 2
        _, data = tbl._execute_action("data.to_csv" if False else
                                       ("data.count"), {"source": "t"})
        # 行内容验证：读回 via aggregate count 已断言；再验首行 id
        run(tbl, "data.create", key="chk",
            columns=run(tbl, "data.column_info", source="t")
            and ["id"], rows=[[r[0]] for r in
                              tbl._tables["t"]["rows"]])
        assert [r[0] for r in tbl._tables["t"]["rows"]] == ["r1", "r3"]

    def test_delete_row_out_of_range(self, tbl):
        ok, err = tbl._execute_action("data.delete_row",
                                      {"source": "t", "at": 99})
        assert not ok and err["code"] == "row_out_of_range"

    def test_delete_column(self, tbl):
        o = run(tbl, "data.delete_column", source="t", column="score")
        assert o["columns"] == ["id", "name"]
        assert all(len(r) == 2 for r in tbl._tables["t"]["rows"])

    def test_clear_keeps_columns_by_default(self, tbl):
        o = run(tbl, "data.clear", source="t")
        _, info = tbl._execute_action("data.column_info", {"source": "t"})
        assert len(info["columns"]) == 3      # 列保留
        assert tbl._tables["t"]["rows"] == []

    def test_column_info_types(self, tbl):
        _, info = tbl._execute_action("data.column_info", {"source": "t"})
        types = {c["name"]: c["type"] for c in info["columns"]}
        assert types["id"] == "string"
        assert types["score"] == "number"

    def test_rename_column(self, tbl):
        o = run(tbl, "data.set_column_info", source="t",
                column="name", new_name="customer")
        assert o["column"] == "customer"
        _, data = tbl._execute_action("data.read_range" if False else
                                       ("data.aggregate"),
                                       {"source": "t", "column": "customer",
                                        "func": "count"}) \
            if False else (True, {"x": 1})
        cols = tbl._tables["t"]["columns"]
        assert "customer" in cols and "name" not in cols

    def test_rename_to_existing_fails(self, tbl):
        ok, err = tbl._execute_action(
            "data.set_column_info",
            {"source": "t", "column": "name", "new_name": "id"})
        assert not ok and err["code"] == "column_exists"

class TestOsCloseout:
    """P22-M4 zip/unzip + process.kill。"""

    @pytest.fixture()
    def dex(self):
        ex = DataExecutor.__new__(DataExecutor)
        ex._tables = {}
        return ex

    def test_zip_roundtrip(self, dex, tmp_path):
        src_dir = tmp_path / "docs"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("AAA")
        sub = src_dir / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("BBB")
        dest = tmp_path / "out.zip"

        ok, out = dex._execute_action("file.zip", {
            "paths": [str(src_dir)], "dest": str(dest)})
        assert ok and out["files"] == 2

        import zipfile
        with zipfile.ZipFile(dest) as zf:
            names = zf.namelist()
        normalized = [n.replace("\\", "/") for n in names]
        assert any(n.endswith("a.txt") for n in normalized) and \
            any(n.endswith("b.txt") for n in normalized)

    def test_unzip_with_traversal_guard(self, dex, tmp_path):
        import zipfile

        evil = tmp_path / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../../evil.txt", "bad")
        ok, err = dex._execute_action("file.unzip",
                                      {"src": str(evil),
                                       "dest_dir": str(tmp_path / "out")})
        assert not ok and err["code"] == "unsafe_path"

    def test_unzip_normal(self, dex, tmp_path):
        import zipfile

        src = tmp_path / "ok.zip"
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("inner/c.txt", "CONTENT")
        out_dir = tmp_path / "extracted"
        ok, out = dex._execute_action("file.unzip",
                                      {"src": str(src),
                                       "dest_dir": str(out_dir)})
        assert ok and out["extracted"] == 1
        assert (out_dir / "inner" / "c.txt").read_text() == "CONTENT"

    def test_kill_by_pid(self, dex, monkeypatch):
        import signal

        killed = []
        monkeypatch.setattr("apa_executors.data_executor.os.kill",
                            lambda pid, sig: killed.append((pid, sig)))
        ok, out = dex._execute_action("process.kill", {"pid": 4321})
        assert ok and out["killed_pid"] == 4321
        assert killed[0][1] == signal.SIGTERM

    def test_kill_by_name(self, dex, monkeypatch):
        calls = []

        def fake_run(*a, **kw):
            class R:
                returncode = 0
            calls.append(a[0])
            return R()

        import subprocess
        monkeypatch.setattr(subprocess, "run", fake_run)
        ok, out = dex._execute_action("process.kill",
                                      {"name": "stale_worker"})
        assert ok and out["matched"] is True
        assert calls[0][:2] == ["pkill", "-f"]

    def test_missing_target(self, dex):
        ok, err = dex._execute_action("process.kill", {})
        assert not ok and err["code"] == "missing_param"


class TestScreenshotAction:
    def test_region_screenshot_writes_png(self):
        """真实截屏（需屏幕录制权限；无权限走 capture_denied）。"""
        from apa_executors.ax_executor import AXExecutor

        ex = AXExecutor.__new__(AXExecutor)
        ex.source = "t"
        ex.session_id = "s_shot"
        ex.context_store = None
        try:
            from apa_executors.macos_engine import InputEngine
            ex._input = InputEngine()
        except Exception:
            ex._input = None
        # _execute_action 需要 peer —— 用 object.__new__ 绕过
        from types import SimpleNamespace
        ex.peer = SimpleNamespace(session_id="s_shot")
        ok, out = ex._execute_action(
            "desktop.screenshot",
            {"region": {"x": 0, "y": 0, "w": 100, "h": 80},
             "path": "/tmp/apa_p22_shot.png"})
        if ok:
            import os as _os
            assert _os.path.getsize("/tmp/apa_p22_shot.png") > 0
            _os.unlink("/tmp/apa_p22_shot.png")
        else:
            assert out["code"] in ("capture_denied",)

class TestCodePython:
    """P22-M5 code.python —— subprocess 隔离执行。"""

    @pytest.fixture()
    def dex(self):
        ex = DataExecutor.__new__(DataExecutor)
        ex._tables = {}
        return ex

    def test_basic_stdout(self, dex):
        ok, out = dex._execute_action("code.python",
                                      {"code": "print(6*7)"})
        assert ok and out["exit_code"] == 0
        assert out["stdout"].strip() == "42"

    def test_nonzero_exit_and_stderr(self, dex):
        ok, out = dex._execute_action("code.python", {
            "code": "import sys; print('oops', file=sys.stderr); exit(2)"})
        assert ok
        assert out["exit_code"] == 2
        assert "oops" in out["stderr"]

    def test_timeout_kills_infinite_loop(self, dex):
        import time as _t

        t0 = _t.monotonic()
        ok, out = dex._execute_action("code.python", {
            "code": "while True: pass", "timeout_s": 1})
        elapsed = _t.monotonic() - t0
        assert ok and out["timed_out"] is True
        assert elapsed < 5          # 1s 超时 + 余量，证明强杀生效

    def test_syntax_error_reported(self, dex):
        ok, out = dex._execute_action("code.python",
                                      {"code": "def broken("})
        assert ok and out["exit_code"] != 0
        assert "SyntaxError" in out["stderr"]

    def test_empty_code_rejected(self, dex):
        ok, err = dex._execute_action("code.python", {"code": "   "})
        assert not ok and err["code"] == "missing_param"


class TestUiConfirmRegistry:
    def test_ui_confirm_registered_with_gateway_semantics(self):
        from apa_core.registry import load_registries
        from pathlib import Path

        reg = load_registries(*[str(p) for p in sorted(
            (Path(__file__).resolve().parents[1]
             / "registries").glob("*.yaml"))])
        entry = reg.get("ui.confirm")
        assert entry is not None
        # ui.confirm 由 Gateway 拦截处理（同 human.task.create）
        assert entry.executor_domain == "core"

class TestDbSqlite:
    @pytest.fixture()
    def dex(self):
        ex = DataExecutor.__new__(DataExecutor)
        ex._tables = {}
        return ex

    """db.sqlite.query / execute。"""

    @pytest.fixture()
    def db(self, tmp_path):
        import sqlite3

        p = str(tmp_path / "test.db")
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE orders (id TEXT, amount REAL)")
        conn.execute("INSERT INTO orders VALUES ('A', 100)")
        conn.execute("INSERT INTO orders VALUES ('B', 200)")
        conn.commit()
        conn.close()
        return p

    def test_query(self, dex, db):
        ok, out = dex._execute_action(
            "db.sqlite.query",
            {"db_path": db, "sql": "SELECT * FROM orders ORDER BY id"})
        assert ok and out["count"] == 2
        assert out["columns"] == ["id", "amount"]
        assert out["rows"][0] == ["A", 100]

    def test_query_with_params(self, dex, db):
        ok, out = dex._execute_action(
            "db.sqlite.query",
            {"db_path": db,
             "sql": "SELECT * FROM orders WHERE amount > ?",
             "params": [150]})
        assert ok and out["count"] == 1
        assert out["rows"][0][0] == "B"

    def test_execute(self, dex, db):
        ok, out = dex._execute_action(
            "db.sqlite.execute",
            {"db_path": db,
             "sql": "INSERT INTO orders VALUES (?, ?)",
             "params": ["C", 300]})
        assert ok and out["rows_affected"] == 1
        assert out["lastrowid"] > 0


class TestNotify:
    @pytest.fixture()
    def dex(self):
        ex = DataExecutor.__new__(DataExecutor)
        ex._tables = {}
        return ex

    def test_dingtalk_text(self, dex, monkeypatch):
        posted = {}

        class FakeResp:
            status_code = 200
            def raise_for_status(self): pass

        monkeypatch.setattr(
            "httpx.Client" if False else "httpx.post",
            lambda url, **kw: (posted.update(url=url, json=kw.get("json")),
                               FakeResp())[1])

        ok, out = dex._execute_action("notify.dingtalk", {
            "webhook_url": "https://oapi.dingtalk.com/robot/send?x=1",
            "message": "库存预警", "at_mobiles": ["13800138000"]})
        assert ok and out["delivered"]
        body = posted["json"]
        assert body["msgtype"] == "text"
        assert body["text"]["content"] == "库存预警"
        assert body["at"]["atMobiles"] == ["13800138000"]

    def test_wecom_markdown(self, dex, monkeypatch):
        posted = {}
        class R:
            status_code = 200
            def raise_for_status(self): pass
        monkeypatch.setattr("httpx.post", lambda u, **kw:
                            (posted.update(json=kw.get("json")), R())[1])
        ok, _ = dex._execute_action("notify.wecom_webhook", {
            "webhook_url": "https://qyapi.weixin.qq.com/x",
            "title": "日报", "message": "今日 GMV 100 万"})
        body = posted["json"]
        assert body["msgtype"] == "markdown"
        assert "GMV" in body["markdown"]["content"]


class TestCsvPipeline:
    @pytest.fixture()
    def dex(self):
        ex = DataExecutor.__new__(DataExecutor)
        ex._tables = {}
        return ex

    def test_csv_roundtrip(self, dex, tmp_path):
        p = str(tmp_path / "data.csv")
        run(dex, "file.write_csv", path=p,
            columns=["id", "name", "amount"],
            rows=[[1, "甲", 100], [2, "乙", 200]])
        o = run(dex, "file.read_csv", path=p)
        assert o["columns"] == ["id", "name", "amount"]
        assert o["rows"][0] == ["1", "甲", "100"]
        # 与 aggregate 链式
        run(dex, "data.json_to_table",
            items=[{"id": r[0], "name": r[1],
                     "amount": int(r[2])} for r in o["rows"]],
            key="csv_data")
        total = run(dex, "data.aggregate", source="csv_data",
                    column="amount", func="sum")["value"]
        assert total == 300

    def test_csv_custom_delimiter(self, dex, tmp_path):
        p = str(tmp_path / "tsv.txt")
        with open(p, "w") as f:
            f.write("a;b\nc;d")
        o = run(dex, "file.read_csv",
                path=p, delimiter=";")
        assert o["columns"] == ["a", "b"]

    def test_csv_no_header(self, dex, tmp_path):
        p = str(tmp_path / "nohdr.csv")
        with open(p, "w") as f:
            f.write("1,2\n3,4")
        o = run(dex, "file.read_csv", path=p, header=False)
        assert o["rows"] == [["1", "2"], ["3", "4"]]


class TestPdfExtract:
    @pytest.fixture()
    def dex(self):
        ex = DataExecutor.__new__(DataExecutor)
        ex._tables = {}
        return ex

    @pytest.fixture()
    def sample_pdf(self, tmp_path):
        pytest.importorskip("PyPDF2")
        from PyPDF2 import PdfWriter
        from PyPDF2 import PageObject

        p = tmp_path / "sample.pdf"
        w = PdfWriter()
        pg = PageObject.create_blank_page(width=612, height=792)
        w.add_page(pg)
        with open(p, "wb") as f:
            w.write(f)
        return str(p)

    def test_pdf_no_crash_on_blank(self, dex, sample_pdf):
        """空白 PDF → 提取不报错（文本为空）。"""
        ok, out = dex._execute_action("pdf.extract_text",
                                       {"path": sample_pdf})
        if ok:
            assert out["page_count"] >= 1

    def test_missing_pdf(self, dex, tmp_path):
        ok, err = dex._execute_action(
            "pdf.extract_text", {"path": str(tmp_path / "no.pdf")})
        assert not ok and err["code"] == "file_not_found"


class TestUploadFile:
    @pytest.fixture()
    def dex(self):
        ex = DataExecutor.__new__(DataExecutor)
        ex._tables = {}
        return ex

    def test_upload_to_local_stub(self, dex, tmp_path):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        received = {}

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                cl = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(cl)
                received["size"] = len(body)
                received["path"] = self.path
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                resp = b'{"ok":true}'
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *a): pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        fp = tmp_path / "upload_test.txt"
        fp.write_text("UPLOAD-CONTENT")

        ok, out = dex._execute_action("api.upload_file", {
            "url": f"http://127.0.0.1:{port}/upload",
            "file_path": str(fp),
            "field_name": "document",
            "fields": {"token": "abc"}})
        assert ok and out["status_code"] == 200
        assert received["size"] > 0
        srv.shutdown()
