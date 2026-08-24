"""email.receive IMAP 测试（Fake imaplib，无网络依赖）。"""
import sys
from email.message import EmailMessage

import pytest

from apa_executors.email_executor import EmailExecutor


class FakeIMAP:
    """最小 IMAP4_SSL 替身：脚本化 search/fetch 输出。"""

    last_instance = None

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.selected_readonly = None
        self.logged_out = False
        FakeIMAP.last_instance = self
        self.msgs = []          # bytes 列表

    def login(self, user, password):
        self.user = user

    def select(self, folder, readonly=False):
        self.selected_readonly = readonly
        return ("OK", [b"1"])

    def search(self, charset, criteria):
        return ("OK", [b" ".join(str(i + 1).encode()
                                 for i in range(len(self.msgs)))])

    def fetch(self, mid, item):
        idx = int(mid) - 1
        raw = self.msgs[idx]
        return ("OK", [(b"1 (RFC822 {size}".replace(b"size",
                   str(len(raw)).encode()), raw), b")"])

    def logout(self):
        self.logged_out = True


def _mime(subject, frm, text="正文"):
    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = frm
    m["Date"] = "Sat, 22 Aug 2026 10:00:00 +0800"
    m.set_content(text)
    return m.as_bytes()


def _ex_with(conn):
    """构造 executor，并把 IMAP4_SSL 指向已配置的假连接。"""
    import imaplib

    ex = EmailExecutor.__new__(EmailExecutor)
    orig = imaplib.IMAP4_SSL
    imaplib.IMAP4_SSL = lambda host, port: conn
    return ex


class TestReceive:
    def test_fetch_and_parse(self):
        conn = FakeIMAP("h", 993)
        conn.msgs = [
            _mime("月度报表", "Boss <boss@corp.com>", "请查收附件"),
            _mime("告警", "ops@corp.com", "磁盘 90%"),
        ]
        ex = _ex_with(conn)
        ok, out = ex._execute_action("email.receive", {
            "host": "imap.corp.com", "username": "bot",
            "password": "pw", "criteria": "UNSEEN", "limit": 10,
        })
        assert ok, out
        assert out["count"] == 2
        # 最新在前
        assert out["messages"][0]["subject"] == "告警"
        assert "boss@corp.com" in out["messages"][1]["from"]
        assert "附件" in out["messages"][1]["text"]
        # 默认 PEEK → readonly=True（不标已读）
        assert conn.selected_readonly is True
        assert conn.logged_out is True

    def test_mark_seen_uses_rfc822(self):
        conn = FakeIMAP("h", 993)
        conn.msgs = [_mime("t", "a@b")]
        ex = _ex_with(conn)
        ok, _ = ex._execute_action("email.receive", {
            "host": "h", "username": "u", "password": "p",
            "mark_seen": True})
        assert ok and conn.selected_readonly is False

    def test_empty_mailbox(self):
        conn = FakeIMAP("h", 993)          # 空邮箱
        ex = _ex_with(conn)
        ok, out = ex._execute_action("email.receive", {
            "host": "h", "username": "u", "password": "p"})
        assert ok and out["count"] == 0

    def test_limit_trims_to_newest(self):
        conn = FakeIMAP("h", 993)
        conn.msgs = [_mime(f"m{i}", f"{i}@x") for i in range(5)]
        ex = _ex_with(conn)
        ok, out = ex._execute_action("email.receive", {
            "host": "h", "username": "u", "password": "p", "limit": 2})
        assert ok and out["count"] == 2
        subjects = [m["subject"] for m in out["messages"]]
        assert subjects == ["m4", "m3"]

    def test_unsupported_action(self):
        ex = EmailExecutor.__new__(EmailExecutor)
        ok, err = ex._execute_action("email.delete_all", {})
        assert not ok