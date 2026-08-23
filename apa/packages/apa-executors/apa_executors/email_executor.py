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
        if name != "email.send":
            return False, {"code": "action_not_supported_by_executor"}
        try:
            return self._send(params)
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