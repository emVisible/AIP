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
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from apa_sdk.executor_base import AIPExecutor


def keep_columns_guard(flag) -> bool:
    return bool(flag)

class DataExecutor(AIPExecutor):
    """数据操作执行器：表格/文件/字符串。"""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._tables: Dict[str, dict] = {}
        self._lists: Dict[str, list] = {}
        self._dicts: Dict[str, dict] = {}

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
            # ---- M1 数据工具包 ----
            "string.regex_extract": self._string_regex_extract,
            "string.regex_replace": self._string_regex_replace,
            "string.regex_test": self._string_regex_test,
            "string.trim": self._string_trim,
            "string.upper": self._string_upper,
            "string.lower": self._string_lower,
            "string.format_template": self._string_format_template,
            "string.pad": self._string_pad,
            "string.starts_with": self._string_starts_with,
            "string.contains": self._string_contains,
            "encode.base64_encode": self._encode_b64_encode,
            "encode.base64_decode": self._encode_b64_decode,
            "encode.url_encode": self._encode_url_encode,
            "encode.url_decode": self._encode_url_decode,
            "json.parse": self._json_parse,
            "json.stringify": self._json_stringify,
            "dt.now": self._dt_now,
            "dt.parse": self._dt_parse,
            "dt.add": self._dt_add,
            "dt.diff": self._dt_diff,
            "dt.timestamp": self._dt_timestamp,
            "hash.md5": self._hash_md5,
            "hash.sha256": self._hash_sha256,
            "uuid.gen": self._uuid_gen,
            "data.aggregate": self._data_aggregate,
            "data.distinct": self._data_distinct,
            "data.slice": self._data_slice,
            "data.json_to_table": self._data_json_to_table,
            "data.merge": self._data_merge,
            # ---- M3 DataTable 收尾 ----
            "data.delete_row": self._data_delete_row,
            "data.delete_column": self._data_delete_column,
            "data.clear": self._data_clear,
            "data.column_info": self._data_column_info,
            "data.set_column_info": self._data_set_column_info,
            # ---- M2 流程控制配套 ----
            "core.delay": self._core_delay,
            "data.count": self._data_count,
            # ---- M4 系统 / 文件 ----
            "shell.execute": self._shell_execute,
            "sys.notify": self._sys_notify,
            "clipboard.set": self._clipboard_set,
            "clipboard.get": self._clipboard_get,
            "file.list_dir": self._file_list_dir,
            "file.mkdir": self._file_mkdir,
            "file.exists": self._file_exists,
            "file.stat": self._file_stat,
            # ---- Phase A 谓词 / 等待 ----
            "if.file_exists": self._if_file_exists,
            "if.dir_exists": self._if_dir_exists,
            "wait.file": self._wait_file,
            # ---- M4 OS 补全 ----
            "file.zip": self._file_zip,
            "file.unzip": self._file_unzip,
            "process.kill": self._process_kill,
            # ---- M5 代码段 ----
            "code.python": self._code_python,
            "file.read_csv": self._file_read_csv,
            "file.write_csv": self._file_write_csv,
            "pdf.extract_text": self._pdf_extract_text,
            "api.upload_file": self._api_upload_file,
            # ---- P22-M2 db + notify ----
            "db.sqlite.query": self._db_sqlite_query,
            "db.sqlite.execute": self._db_sqlite_execute,
            "notify.dingtalk": self._notify_dingtalk,
            "notify.wecom_webhook": self._notify_wecom,
            "notify.feishu_webhook": self._notify_feishu,
            # ---- P24-M1 列表/字典 ----
            "list.create": self._list_create,
            "list.append": self._list_append,
            "list.insert": self._list_insert,
            "list.remove_at": self._list_remove_at,
            "list.remove_value": self._list_remove_value,
            "list.get": self._list_get,
            "list.set": self._list_set,
            "list.length": self._list_length,
            "list.reverse": self._list_reverse,
            "list.sort": self._list_sort,
            "dict.create": self._dict_create,
            "dict.get": self._dict_get,
            "dict.set": self._dict_set,
            "dict.has_key": self._dict_has_key,
            "dict.keys": self._dict_keys,
            "dict.values": self._dict_values,
            "dict.remove": self._dict_remove,
        }
        fn = handler_map.get(name)
        if fn is None:
            return False, {"code": "action_not_supported_by_executor"}
        try:
            return fn(params)
        except Exception as e:
            return False, {"code": type(e).__name__, "detail": str(e)}

    # ==== M1 数据工具包 =====================================================

    # ---- string.* -----------------------------------------------------------

    def _string_regex_extract(self, p):
        import re as _re

        text = p.get("text", "")
        pattern = p["pattern"]
        flags = 0
        if p.get("ignore_case"):
            flags |= _re.IGNORECASE
        matches = [m.group(int(p.get("group", 0)))
                   for m in _re.finditer(pattern, text, flags)]
        return True, {"matches": matches, "count": len(matches),
                      "first": matches[0] if matches else ""}

    def _string_regex_replace(self, p):
        import re as _re

        out = _re.sub(p["pattern"], p.get("repl", ""), p.get("text", ""))
        return True, {"result": out}

    def _string_regex_test(self, p):
        import re as _re

        ok = _re.search(p["pattern"], p.get("text", "")) is not None
        return True, {"matched": ok}

    def _string_trim(self, p):
        return True, {"result": str(p.get("text", "")).strip()}

    def _string_upper(self, p):
        return True, {"result": str(p.get("text", "")).upper()}

    def _string_lower(self, p):
        return True, {"result": str(p.get("text", "")).lower()}

    def _string_format_template(self, p):
        """{name} 占位模板；缺变量保留原样。"""
        import re as _re

        vars_ = p.get("vars") or {}
        tpl = p.get("template", "")
        out = _re.sub(r"\{(\w+)\}",
                      lambda m: str(vars_.get(m.group(1), m.group(0))),
                      tpl)
        return True, {"result": out}

    def _string_pad(self, p):
        """align 指填充侧：left=左补齐(rjust)，right=右补齐(ljust)。"""
        text = str(p.get("text", ""))
        width = int(p.get("width", 0))
        fill = str(p.get("fillchar", " "))[:1] or " "
        align = p.get("align", "left")
        fn = {"left": text.rjust, "right": text.ljust,
              "center": text.center}.get(align, text.rjust)
        return True, {"result": fn(width, fill)}

    def _string_starts_with(self, p):
        return True, {"matched":
                      str(p.get("text", "")).startswith(str(p.get("prefix", "")))}

    def _string_contains(self, p):
        needle = str(p.get("needle", ""))
        hay = str(p.get("text", ""))
        if p.get("ignore_case"):
            ok = needle.lower() in hay.lower()
        else:
            ok = needle in hay
        return True, {"matched": ok}

    # ---- encode.* -----------------------------------------------------------

    def _encode_b64_encode(self, p):
        import base64

        raw = p.get("text", "")
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        return True, {"result":
                      base64.b64encode(data).decode("ascii")}

    def _encode_b64_decode(self, p):
        import base64

        out = base64.b64decode(p.get("b64", ""))
        try:
            return True, {"result": out.decode("utf-8")}
        except UnicodeDecodeError:
            return True, {"result_b64": base64.b64encode(out).decode()}

    def _encode_url_encode(self, p):
        from urllib.parse import quote

        return True, {"result":
                      quote(str(p.get("text", "")), safe="")}

    def _encode_url_encode_component(self, p):
        from urllib.parse import quote

        return True, {"result":
                      quote(str(p.get("text", "")), safe="")}

    def _encode_url_decode(self, p):
        from urllib.parse import unquote

        return True, {"result": unquote(str(p.get("text", "")))}

    # ---- json.* -------------------------------------------------------------

    def _json_parse(self, p):
        import json as _j

        val = _j.loads(p.get("text", "{}"))
        return True, {"value": val}

    def _json_stringify(self, p):
        import json as _j

        indent = p.get("indent")
        return True, {"text": _j.dumps(
            p.get("value"), ensure_ascii=False,
            indent=int(indent) if indent else None,
            default=str)}

    # ---- dt.* ---------------------------------------------------------------

    @staticmethod
    def _fmt_dt(d, fmt: Optional[str]) -> str:
        return d.strftime(fmt) if fmt else d.isoformat()

    def _dt_now(self, p):
        from datetime import datetime

        now = datetime.now()
        return True, {
            "iso": now.isoformat(),
            "formatted": self._fmt_dt(now, p.get("fmt")),
            "epoch": now.timestamp(),
        }

    def _dt_parse(self, p):
        from datetime import datetime

        d = (datetime.strptime(p["text"], p["fmt"])
             if p.get("fmt") else datetime.fromisoformat(p["text"]))
        return True, {"iso": d.isoformat(), "epoch": d.timestamp()}

    def _dt_add(self, p):
        from datetime import datetime, timedelta

        base = (datetime.strptime(p["iso"], p["fmt"])
                if p.get("fmt") else datetime.fromisoformat(p["iso"]))
        delta = timedelta(
            days=float(p.get("days", 0)),
            hours=float(p.get("hours", 0)),
            minutes=float(p.get("minutes", 0)),
            seconds=float(p.get("seconds", 0)))
        out = base + delta
        return True, {"iso": out.isoformat(),
                      "formatted": self._fmt_dt(out, p.get("fmt"))}

    def _dt_diff(self, p):
        from datetime import datetime

        a = datetime.fromisoformat(p["a"])
        b = datetime.fromisoformat(p["b"])
        sec = (b - a).total_seconds()
        unit = p.get("unit", "seconds")
        div = {"seconds": 1, "minutes": 60, "hours": 3600,
               "days": 86400}.get(unit, 1)
        return True, {"value": sec / div, "unit": unit}

    def _dt_timestamp(self, p):
        from datetime import datetime, timezone

        d = (datetime.strptime(p["iso"], p["fmt"])
             if p.get("fmt") else datetime.fromisoformat(p["iso"]))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)  # 无时区按 UTC
        return True, {"epoch": d.timestamp()}

    # ---- hash / uuid --------------------------------------------------------

    def _hash_md5(self, p):
        import hashlib

        return True, {"digest": hashlib.md5(
            str(p.get("text", "")).encode()).hexdigest()}

    def _hash_sha256(self, p):
        import hashlib

        return True, {"digest": hashlib.sha256(
            str(p.get("text", "")).encode()).hexdigest()}

    def _uuid_gen(self, p):
        import uuid as _u

        return True, {"uuid": str(_u.uuid4())}

    # ---- data 增强 ----------------------------------------------------------

    def _data_aggregate(self, p):
        src = self._get_table(p.get("source", ""))
        col = p["column"]
        func = p.get("func", "sum")
        idx = src["columns"].index(col)
        vals = [float(r[idx]) for r in src["rows"] if r[idx] is not None]
        if not vals:
            return True, {"value": 0}
        fn = {"sum": sum,
              "avg": lambda v: sum(v) / len(v),
              "min": min, "max": max,
              "count": lambda v: len(v)}.get(func)
        if fn is None:
            return False, {"code": f"unknown func {func!r}"}
        return True, {"value": round(fn(vals), 6), "func": func}

    def _data_distinct(self, p):
        src = self._get_table(p.get("source", ""))
        col = p["column"]
        idx = src["columns"].index(col)
        seen = set()
        rows = []
        for r in src["rows"]:
            key = r[idx]
            mark = json.dumps(key, sort_keys=True, default=str)
            if mark not in seen:
                seen.add(mark)
                rows.append(list(r))
        out_key = p.get("output_key", "distinct")
        result = {"columns": list(src["columns"]), "rows": rows,
                  "count": len(rows)}
        self._set_table(out_key, result)
        return True, {**result}

    def _data_slice(self, p):
        src = self._get_table(p.get("source", ""))
        start = int(p.get("start", 0))
        stop = p.get("stop")
        rows = src["rows"][start:(int(stop) if stop is not None else None)]
        out_key = p.get("output_key", "sliced")
        result = {"columns": list(src["columns"]), "rows": rows,
                  "count": len(rows)}
        self._set_table(out_key, result)
        return True, {**result}

    def _data_json_to_table(self, p):
        items = p.get("items") or []
        columns: List[str] = []
        for it in items:
            if isinstance(it, dict):
                for k in it.keys():
                    if k not in columns:
                        columns.append(k)
        rows = [[it.get(c) for c in columns] for it in items]
        table = {"columns": columns, "rows": rows}
        self._set_table(p.get("key", "from_json"), table)
        return True, {**table, "count": len(rows)}

    def _core_delay(self, p):
        """等待 N 秒（上限 300s 防误配挂死会话线程）。"""
        import time as _t

        seconds = float(p.get("seconds", 0))
        if seconds <= 0:
            return True, {"slept": 0.0}
        slept = min(seconds, 300.0)
        _t.sleep(slept)
        return True, {"slept": round(slept, 3)}

    def _data_count(self, p):
        src = self._get_table(p.get("source", ""))
        return True, {"count": len(src.get("rows", []))}

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

    # ==== M4 系统 / 文件 =====================================================

    def _shell_execute(self, p):
        """执行 shell 命令。L2：审计记录 cmd；超时强杀。"""
        import subprocess

        cmd = str(p.get("cmd", ""))
        if not cmd.strip():
            return False, {"code": "missing_param", "detail": "cmd"}
        timeout_s = min(float(p.get("timeout_s", 30)), 600)
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=timeout_s)
            return True, {
                "exit_code": r.returncode,
                "stdout": (r.stdout or "")[-20000:],
                "stderr": (r.stderr or "")[-5000:],
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as e:
            return True, {
                "exit_code": None, "stdout": "", 
                "stderr": f"timeout after {timeout_s}s",
                "timed_out": True,
            }

    def _sys_notify(self, p):
        """macOS 通知中心（osascript）；非 darwin 降级 stdout。"""
        import subprocess
        import sys

        title = str(p.get("title", "APA"))
        message = str(p.get("message", "")).replace(chr(34), chr(92) + chr(34))
        if sys.platform == "darwin":
            script = (f'display notification "{message}" '
                      f'with title "{title}"')
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=10)
            return True, {"delivered": r.returncode == 0,
                          "channel": "notification_center"}
        print(f"[notify] {title}: {message}")
        return True, {"delivered": True, "channel": "stdout"}

    def _clipboard_set(self, p):
        try:
            from .macos_engine import Clipboard

            Clipboard.copy(str(p.get("text", "")))
            return True, {"set": True}
        except Exception as e:  # noqa: BLE001
            return False, {"code": "clipboard_unavailable",
                           "detail": str(e)[:80]}

    def _clipboard_get(self, p):
        try:
            from .macos_engine import Clipboard

            return True, {"text": Clipboard.paste_text()}
        except Exception as e:  # noqa: BLE001
            return False, {"code": "clipboard_unavailable",
                           "detail": str(e)[:80]}

    def _file_list_dir(self, p):
        base = Path(p["path"])
        pattern = p.get("pattern") or "*"
        entries = []
        for fp in sorted(base.glob(pattern)):
            try:
                stat = fp.stat()
                size = stat.st_size
                is_dir = fp.is_dir()
            except OSError:
                size, is_dir = None, fp.is_dir()
            entries.append({"name": fp.name, "is_dir": is_dir,
                            "size": size})
        return True, {"entries": entries, "count": len(entries),
                      "path": str(base)}

    def _file_mkdir(self, p):
        path = Path(p["path"])
        parents = bool(p.get("parents", True))
        existed = path.exists()
        path.mkdir(parents=parents, exist_ok=True)
        return True, {"path": str(path), "existed": existed}

    def _file_exists(self, p):
        return True, {"exists": Path(p["path"]).exists()}

    def _file_stat(self, p):
        from datetime import datetime

        fp = Path(p["path"])
        if not fp.exists():
            return False, {"code": "file_not_found"}
        st = fp.stat()
        return True, {
            "size": st.st_size,
            "mtime_iso": datetime.fromtimestamp(
                st.st_mtime).isoformat(),
            "is_dir": fp.is_dir(),
        }

    def _data_merge(self, p):
        """两表拼接 concat（纵向）或按键 inner/left 连接。"""
        a = self._get_table(p.get("a", ""))
        b = self._get_table(p.get("b", ""))
        how = p.get("how", "concat")
        out_key = p.get("output_key", "merged")

        if how == "concat":
            cols = list(a["columns"])
            for c in b["columns"]:
                if c not in cols:
                    cols.append(c)
            def pad(row, tbl_cols):
                return [row[tbl_cols.index(c)] if c in tbl_cols else None
                        for c in cols]
            rows = [pad(r, a["columns"]) for r in a["rows"]] + \
                   [pad(r, b["columns"]) for r in b["rows"]]
            result = {"columns": cols, "rows": rows, "count": len(rows)}
            self._set_table(out_key, result)
            return True, {**result}

        on = p.get("on")
        if not on:
            return False, {"code": "missing_param",
                           "detail": "on required for join modes"}
        ai = a["columns"].index(on) if on in a["columns"] else None
        bi = b["columns"].index(on) if on in b["columns"] else None
        if ai is None or bi is None:
            return False, {"code": "join_key_missing", "column": on}

        cols = list(a["columns"]) + [c for c in b["columns"] if c != on]
        b_index = {}
        for row in b["rows"]:
            b_index.setdefault(json.dumps(row[bi], sort_keys=True,
                                          default=str), row)
        rows = []
        for ra in a["rows"]:
            key = json.dumps(ra[ai], sort_keys=True, default=str)
            rb = b_index.get(key)
            if rb is not None:
                extra = [v for j, v in enumerate(rb)
                         if j != bi]
                rows.append(list(ra) + extra)
            elif how == "left":
                rows.append(list(ra) +
                            [None] * (len(cols) - len(a["columns"])))
        result = {"columns": cols, "rows": rows, "count": len(rows)}
        self._set_table(out_key, result)
        return True, {**result}

    def _if_file_exists(self, p):
        from pathlib import Path as _P

        return True, {"matched": _P(str(p.get("path", ""))).is_file()}

    def _if_dir_exists(self, p):
        from pathlib import Path as _P

        return True, {"matched": _P(str(p.get("path", ""))).is_dir()}

    def _wait_file(self, p):
        """轮询等待 glob 首个命中文件。返回 {path}。"""
        import time as _t

        from pathlib import Path as _P

        pattern = str(p.get("glob", "")).strip()
        if not pattern:
            return False, {"code": "missing_param", "detail": "glob"}
        timeout_s = min(float(p.get("timeout_s", 30.0)), 600.0)
        interval = max(float(p.get("interval_s", 0.5)), 0.05)
        g = _P(pattern)
        deadline = _t.monotonic() + timeout_s
        while _t.monotonic() < deadline:
            hits = sorted(g.parent.glob(g.name)) if g.parent.exists() else []
            if hits:
                return True, {"path": str(hits[0])}
            _t.sleep(interval)
        return False, {"code": "wait_timeout", "glob": pattern,
                       "timeout_s": timeout_s}

    def _data_delete_row(self, p):
        src_key = p.get("source", "default")
        tbl = self._get_table(src_key)
        idx = int(p["at"])
        if 0 <= idx < len(tbl["rows"]):
            tbl["rows"].pop(idx)
        else:
            return False, {"code": "row_out_of_range",
                           "at": idx, "rows": len(tbl["rows"])}
        self._set_table(src_key, tbl)
        return True, {"count": len(tbl["rows"])}

    def _data_delete_column(self, p):
        src_key = p.get("source", "default")
        tbl = self._get_table(src_key)
        col = str(p["column"])
        if col not in tbl["columns"]:
            return False, {"code": "column_not_found", "column": col}
        ci = tbl["columns"].index(col)
        tbl["columns"].pop(ci)
        for r in tbl["rows"]:
            if ci < len(r):
                r.pop(ci)
        self._set_table(src_key, tbl)
        return True, {"columns": list(tbl["columns"])}

    def _data_clear(self, p):
        src_key = p.get("source", "default")
        keep_cols = bool(p.get("keep_columns", True))
        cols = list(self._get_table(src_key)["columns"]) \
            if keep_columns_guard(keep_cols) else []
        self._set_table(src_key,
                        {"columns": cols, "rows": []})
        return True, {"cleared": True, "kept_columns": bool(cols)}

    def _data_column_info(self, p):
        """列信息：名称+类型推断+非空计数。"""
        tbl = self._get_table(p.get("source", ""))
        infos = []
        for ci, col in enumerate(tbl["columns"]):
            vals = [r[ci] for r in tbl["rows"] if ci < len(r)]
            non_null = [v for v in vals if v is not None]
            t = "empty"
            if non_null:
                if all(isinstance(v, (int, float))
                        and not isinstance(v, bool) for v in non_null):
                    t = "number"
                elif all(isinstance(v, bool) for v in non_null):
                    t = "boolean"
                else:
                    t = "string"
            infos.append({"name": str(col), "type": t,
                          "non_null": len(non_null),
                          "total": len(tbl["rows"])})
        return True, {"columns": infos}

    def _data_set_column_info(self, p):
        """设置列显示名（重命名）与类型标注（仅元信息，不改值）。"""
        tbl = self._get_table(p.get("source", ""))
        col = str(p["column"])
        new_name = p.get("new_name")
        type_tag = p.get("type_tag")
        meta = tbl.setdefault("_meta", {})
        col_meta = meta.setdefault(col, {})
        if new_name:
            if new_name in tbl["columns"] and new_name != col:
                return False, {"code": "column_exists",
                               "column": new_name}
            ci = tbl["columns"].index(col)
            tbl["columns"][ci] = new_name
            col_meta = meta.pop(col, {})
            meta[new_name] = col_meta
            col = new_name
        if type_tag:
            col_meta["type_tag"] = str(type_tag)
        self._set_table(p.get("source", "default"), tbl)
        return True, {"column": col,
                      **col_meta}

    def _file_zip(self, p):
        """打包文件/目录到 zip（目录递归；原子落盘）。"""
        import os
        import zipfile

        dest = str(p["dest"])
        sources = [str(x) for x in (p.get("paths") or [])]
        if not sources:
            return False, {"code": "missing_param", "detail": "paths"}
        d = os.path.dirname(dest) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".zip", dir=d)
        os.close(fd)
        count = 0
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                for src in sources:
                    sp = Path(src)
                    if sp.is_dir():
                        for root, _, files in os.walk(sp):
                            for fn in files:
                                full = Path(root) / fn
                                arc = str(full.relative_to(sp.parent))
                                zf.write(full, arc)
                                count += 1
                    elif sp.is_file():
                        zf.write(sp, sp.name)
                        count += 1
            os.replace(tmp, dest)
            return True, {"dest": dest, "files": count}
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _file_unzip(self, p):
        import zipfile

        src = str(p["src"])
        dest_dir = str(p.get("dest_dir") or
                        Path(src).parent / Path(src).stem)
        if not Path(src).is_file():
            return False, {"code": "file_not_found", "src": src}
        os.makedirs(dest_dir, exist_ok=True)
        extracted = 0
        with zipfile.ZipFile(src) as zf:
            for name in zf.namelist():
                target = (Path(dest_dir) / name).resolve()
                if not str(target).startswith(
                        str(Path(dest_dir).resolve())):
                    return False, {"code": "unsafe_path", "entry": name}
            zf.extractall(dest_dir)
            extracted = len(zf.namelist())
        return True, {"dest_dir": dest_dir, "extracted": extracted}

    def _process_kill(self, p):
        """终止进程：pid 或按名称模糊匹配（darwin: pkill）。"""
        import signal
        import subprocess

        pid = p.get("pid")
        name = p.get("name")
        if pid is None and not name:
            return False, {"code": "missing_param",
                           "detail": "pid or name"}
        if pid is not None:
            os.kill(int(pid), signal.SIGTERM)
            return True, {"killed_pid": int(pid)}
        r = subprocess.run(["pkill", "-f", str(name)],
                           capture_output=True, timeout=10)
        return True, {"matched": r.returncode == 0,
                      "pattern": str(name)}

    def _code_python(self, p):
        """独立 subprocess 执行 Python 片段。

        安全形态：进程隔离 + timeout SIGKILL + 完整代码入审计
        （risk=L3 → PolicyConfig 默认策略强制人工审批后才到达此处）。
        """
        import subprocess

        code = str(p.get("code", ""))
        if not code.strip():
            return False, {"code": "missing_param", "detail": "code"}
        timeout_s = min(float(p.get("timeout_s", 30)), 600)
        try:
            r = subprocess.run([sys.executable, "-c", code],
                               capture_output=True, text=True,
                               timeout=timeout_s)
            return True, {
                "exit_code": r.returncode,
                "stdout": (r.stdout or "")[-20000:],
                "stderr": (r.stderr or "")[-5000:],
                "timed_out": False,
            }
        except subprocess.TimeoutExpired:
            return True, {"exit_code": None, "stdout": "", "stderr": "",
                          "timed_out": True,
                          "detail": f"killed after {timeout_s}s"}
        except Exception as e:  # noqa: BLE001
            return False, {"code": type(e).__name__, "detail": str(e)[:120]}


    def _db_sqlite_query(self, p):
        """SQLite 查询 → {columns, rows, count}。"""
        import sqlite3

        db_path = str(p["db_path"])
        sql = str(p["sql"])
        params = p.get("params") or []
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(sql, params)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = [[v for v in row] for row in cur.fetchall()]
            return True, {"columns": cols, "rows": rows,
                           "count": len(rows)}
        finally:
            conn.close()

    def _db_sqlite_execute(self, p):
        import sqlite3

        db_path = str(p["db_path"])
        sql = str(p["sql"])
        params = p.get("params") or []
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return True, {"rows_affected": cur.rowcount,
                           "lastrowid": cur.lastrowid}
        finally:
            conn.close()

    def _post_webhook(self, url: str, body: dict) -> Tuple[bool, dict]:
        import httpx

        resp = httpx.post(url, json=body, timeout=15.0)
        resp.raise_for_status()
        return True, {"delivered": True, "status": resp.status_code}

    def _notify_dingtalk(self, p):
        """钉钉群机器人 webhook。"""
        url = str(p.get("webhook_url", ""))
        if not url:
            return False, {"code": "missing_param", "detail": "webhook_url"}
        body: Dict[str, Any] = {
            "msgtype": p.get("msgtype", "text"),
        }
        if body["msgtype"] == "markdown":
            body["markdown"] = {
                "title": str(p.get("title", "APA")),
                "text": str(p.get("message", "")),
            }
        else:
            body["text"] = {"content": str(p.get("message", ""))}
        if p.get("at_mobiles"):
            body["at"] = {"atMobiles": p["at_mobiles"]}
        return self._post_webhook(url, body)

    def _notify_wecom(self, p):
        """企业微信群机器人 webhook。"""
        url = str(p.get("webhook_url", ""))
        if not url:
            return False, {"code": "missing_param", "detail": "webhook_url"}
        md = str(p.get("message", ""))
        content = f"## {p.get('title', 'APA')}\n{md}" \
            if p.get("title") else md
        return self._post_webhook(url, {
            "msgtype": "markdown",
            "markdown": {"content": content[:4000]},
        })

    def _notify_feishu(self, p):
        """飞书群机器人 webhook。"""
        url = str(p.get("webhook_url", ""))
        if not url:
            return False, {"code": "missing_param", "detail": "webhook_url"}
        return self._post_webhook(url, {
            "msg_type": "text",
            "content": {"text":
                f"{p.get('title', 'APA')}: {p.get('message', '')}"},
        })

    # ==== P24-M1 列表操作 =====================================================

    def _get_list(self, key: str) -> list:
        return self._lists.get(key, [])

    def _list_create(self, p):
        key = str(p.get("key", "my_list"))
        items = p.get("items") or []
        self._lists[key] = list(items)
        return True, {"key": key, "count": len(items)}

    def _list_append(self, p):
        key = str(p.get("key", "my_list"))
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].append(p.get("item"))
        return True, {"count": len(self._lists[key])}

    def _list_insert(self, p):
        key = str(p.get("key", "my_list"))
        idx = int(p.get("index", 0))
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].insert(idx, p.get("item"))
        return True, {"count": len(self._lists[key])}

    def _list_remove_at(self, p):
        key = str(p.get("key", "my_list"))
        idx = int(p["index"])
        lst = self._get_list(key)
        if 0 <= idx < len(lst):
            removed = lst.pop(idx)
            return True, {"removed": removed}
        return False, {"code": "index_out_of_range"}

    def _list_remove_value(self, p):
        key = str(p.get("key", "my_list"))
        val = p.get("value")
        lst = self._get_list(key)
        try:
            lst.remove(val)
            return True, {"removed": val}
        except ValueError:
            return False, {"code": "value_not_found", "value": val}

    def _list_get(self, p):
        key = str(p.get("key", "my_list"))
        idx = int(p["index"])
        lst = self._get_list(key)
        if 0 <= idx < len(lst):
            return True, {"value": lst[idx]}
        return False, {"code": "index_out_of_range"}

    def _list_set(self, p):
        key = str(p.get("key", "my_list"))
        idx = int(p["index"])
        lst = self._get_list(key)
        if 0 <= idx < len(lst):
            lst[idx] = p.get("item")
            return True, {"updated": idx}
        return False, {"code": "index_out_of_range"}

    def _list_length(self, p):
        return True, {"count": len(self._get_list(str(p.get("key", ""))))}

    def _list_reverse(self, p):
        key = str(p.get("key", ""))
        lst = self._get_list(key)
        lst.reverse()
        self._lists[key] = lst
        return True, {"count": len(lst)}

    def _list_sort(self, p):
        import operator

        key_name = str(p.get("key", ""))
        reverse = bool(p.get("reverse", False))
        sort_key = p.get("sort_key")
        lst = self._get_list(key_name)
        try:
            if sort_key and all(isinstance(x, dict) for x in lst):
                sk = str(sort_key)
                lst.sort(key=operator.itemgetter(sk), reverse=reverse)
            else:
                lst.sort(reverse=reverse)
            self._lists[key_name] = lst
            return True, {"count": len(lst)}
        except TypeError as e:
            return False, {"code": "sort_failed", "detail": str(e)}

    # ==== P24-M1 字典操作 =====================================================

    def _get_dict(self, key: str) -> dict:
        return self._dicts.get(key, {})

    def _dict_create(self, p):
        key = str(p.get("key", "my_dict"))
        initial = p.get("initial") or {}
        self._dicts[key] = dict(initial)
        return True, {"key": key, "count": len(initial)}

    def _dict_get(self, p):
        d = self._get_dict(str(p.get("key", "")))
        k = p.get("k", p.get("key2", ""))
        default = p.get("default")
        val = d.get(k, default)
        return True, {"value": val}

    def _dict_set(self, p):
        key = str(p.get("key", "my_dict"))
        if key not in self._dicts:
            self._dicts[key] = {}
        k = str(p.get("k", ""))
        self._dicts[key][k] = p.get("v")
        return True, {"count": len(self._dicts[key])}

    def _dict_has_key(self, p):
        d = self._get_dict(str(p.get("key", "")))
        return True, {"exists": str(p.get("k", "")) in d}

    def _dict_keys(self, p):
        d = self._get_dict(str(p.get("key", "")))
        return True, {"keys": list(d.keys())}

    def _dict_values(self, p):
        d = self._get_dict(str(p.get("key", "")))
        return True, {"values": list(d.values())}

    def _dict_remove(self, p):
        key = str(p.get("key", ""))
        k = str(p.get("k", ""))
        d = self._get_dict(key)
        if k in d:
            del d[k]
            return True, {"removed": k}
        return False, {"code": "key_not_found"}

    def _file_read_csv(self, p):
        """CSV → {columns, rows, count}（与 data.create 输出对齐）。"""
        import csv as _csv

        path = str(p["path"])
        encoding = str(p.get("encoding", "utf-8-sig"))
        delimiter = str(p.get("delimiter", ","))
        has_header = bool(p.get("header", True))
        with open(path, encoding=encoding, newline="") as f:
            reader = _csv.reader(f, delimiter=delimiter)
            raw = [row for row in reader if row]
        columns = [str(c) for c in raw[0]] if (has_header and raw) else []
        rows = raw[1:] if (has_header and raw) else raw
        return True, {"columns": columns, "rows": rows,
                       "count": len(rows)}

    def _file_write_csv(self, p):
        import csv as _csv

        path = str(p["path"])
        columns = p.get("columns") or []
        rows = p.get("rows") or []
        encoding = str(p.get("encoding", "utf-8-sig"))
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".csv", dir=d)
        try:
            with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
                w = _csv.writer(f)
                if columns:
                    w.writerow(columns)
                w.writerows(rows)
            os.replace(tmp, path)
            return True, {"path": path, "rows": len(rows)}
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _pdf_extract_text(self, p):
        """提取 PDF 文本（PyPDF2，纯 Python 零系统依赖）。"""
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return False, {"code": "dependency_missing",
                           "detail": "uv pip install PyPDF2"}
        path = str(p["path"])
        if not Path(path).is_file():
            return False, {"code": "file_not_found", "path": path}
        reader = PdfReader(path)
        max_pages = int(p.get("max_pages", 50))
        pages = []
        for i, pg in enumerate(reader.pages[:max_pages]):
            txt = pg.extract_text() or ""
            pages.append({"page": i + 1, "text": txt})
        full = "\n".join(pg["text"] for pg in pages)
        return True, {
            "pages": pages, "page_count": len(pages),
            "total_chars": len(full), "text": full[:50000],
        }

    def _api_upload_file(self, p):
        """multipart/form-data 文件上传。"""
        import httpx

        url = str(p["url"])
        field_name = str(p.get("field_name", "file"))
        file_path = str(p["file_path"])
        extra_fields = p.get("fields") or {}
        headers = p.get("headers") or {}
        if not Path(file_path).is_file():
            return False, {"code": "file_not_found", "path": file_path}
        with open(file_path, "rb") as f:
            files = {field_name: (Path(file_path).name, f)}
            resp = httpx.post(url, files=files, data=extra_fields,
                              headers=headers, timeout=60.0,
                              follow_redirects=True)
        resp.raise_for_status()
        return True, {"status_code": resp.status_code,
                       "response": resp.text[:2000]}
