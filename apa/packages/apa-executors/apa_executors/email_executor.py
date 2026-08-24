"""apa-executors: SMTP 邮件发送执行器（对标影刀邮件指令）。

动作域：email.send
使用 stdlib smtplib + email.mime，无外部依赖。
凭据（host/port/user/pass）通过 Vault 凭据注入或 params 传入。
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from pathlib import Path
from typing import Tuple


class EmailExecutor:
    """SMTP 邮件发送。"""

    def start_observation(self) -> None:
        pass

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        handlers = {
            "email.send": self._send,
            "email.receive": self._receive,
        }
        fn = handlers.get(name)
        if fn is None:
            return False, {"code": "action_not_supported_by_executor"}
        try:
            return fn(params)
        except smtplib.SMTPAuthenticationError as e:
            return False, {"code": "smtp_auth_failed", "detail": str(e)}
        except smtplib.SMTPConnectError as e:
            return False, {"code": "smtp_connect_failed", "detail": str(e)}
        except Exception as e:
            return False, {"code": type(e).__name__, "detail": str(e)}

    def _send(self, p: dict) -> Tuple[bool, dict]:
        host = p.get("smtp_host", "")
        port = int(p.get("smtp_port", 587))
        user = p.get("username", "")
        password = p.get("password", "")
        use_tls = p.get("use_tls", True)

        msg = MIMEMultipart()
        msg["From"] = p.get("from") or user
        msg["To"] = p["to"]
        cc = p.get("cc")
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = p.get("subject", "")

        body_type = p.get("body_type", "plain")
        msg.attach(MIMEText(p.get("body", ""), body_type, "utf-8"))

        for att_path in p.get("attachments") or []:
            fp = Path(att_path)
            if fp.is_file():
                part = MIMEBase("application", "octet-stream")
                part.set_payload(fp.read_bytes())
                from email import encoders
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={fp.name}",
                )
                msg.attach(part)

        with smtplib.SMTP(host, port, timeout=30) as srv:
            if use_tls:
                srv.starttls()
            if user and password:
                srv.login(user, password)
            recipients = [p["to"]]
            if cc:
                recipients.extend(cc.split(","))
            srv.send_message(msg)

        return True, {"sent": True, "to": p["to"], "subject": p.get("subject")}

    # ---- M2 收件（IMAP）------------------------------------------------------

    def _receive(self, p: dict) -> Tuple[bool, dict]:
        """IMAP 拉取邮件 → 结构化列表。

        params: host/port(993)/username/password/folder=INBOX/
                criteria=UNSEEN/limit=10/mark_seen=False
        返回 messages: [{from,subject,date,text}]
        """
        import email as _em
        import imaplib
        from email.header import decode_header

        def _decode(raw) -> str:
            if raw is None:
                return ""
            parts = decode_header(str(raw))
            out = []
            for data, charset in parts:
                if isinstance(data, bytes):
                    out.append(data.decode(charset or "utf-8", "replace"))
                else:
                    out.append(str(data))
            return "".join(out)

        def _body(msg) -> str:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            cs = part.get_content_charset() or "utf-8"
                            return payload.decode(cs, "replace")
                return ""
            payload = msg.get_payload(decode=True)
            if payload is None:
                return str(payload or "")
            cs = msg.get_content_charset() or "utf-8"
            return payload.decode(cs, "replace")

        host = p.get("host", "")
        port = int(p.get("port", 993))
        user = p.get("username", "")
        password = str(p.get("password", ""))
        folder = p.get("folder", "INBOX")
        criteria = p.get("criteria", "UNSEEN")
        limit = int(p.get("limit", 10))
        mark_seen = bool(p.get("mark_seen", False))

        conn = imaplib.IMAP4_SSL(host, port)
        try:
            conn.login(user, password)
            conn.select(folder, readonly=not mark_seen)
            status, data = conn.search(None, criteria)
            if status != "OK":
                return False, {"code": "imap_search_failed",
                               "status": status}
            ids = data[0].split()[-limit:] if data and data[0] else []
            messages = []
            for mid in reversed(ids):     # 最新在前
                fetch_item = "(RFC822)" if mark_seen else "(BODY.PEEK[])"
                st, fetched = conn.fetch(mid, fetch_item)
                if st != "OK" or not fetched or fetched[0] is None:
                    continue
                raw = fetched[0][1]
                msg = _em.message_from_bytes(raw)
                messages.append({
                    "from": _decode(msg.get("From")),
                    "subject": _decode(msg.get("Subject")),
                    "date": str(msg.get("Date", "")),
                    "text": _body(msg)[:5000],
                })
            return True, {"messages": messages, "count": len(messages)}
        finally:
            try:
                conn.logout()
            except Exception:
                pass
