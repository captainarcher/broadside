"""Notification dispatch for Broadside — osascript, webhook, SMTP."""

from __future__ import annotations

import json
import smtplib
import subprocess
from email.mime.text import MIMEText

import httpx

from .config import BroadsideConfig, NotifyOsascript, NotifyWebhook, NotifySmtp


def send_notifications(config: BroadsideConfig, subject: str, body: str) -> None:
    for notifier in config.notify:
        try:
            if isinstance(notifier, NotifyOsascript):
                _send_osascript(subject, body)
            elif isinstance(notifier, NotifyWebhook):
                _send_webhook(notifier.url, subject, body)
            elif isinstance(notifier, NotifySmtp):
                _send_smtp(notifier, subject, body)
        except Exception as e:
            # Log but don't crash — partial notification is better than none
            print(f"Notification failed ({notifier.type}): {e}")


def _send_osascript(title: str, body: str) -> None:
    # Truncate body for macOS notification (max ~256 chars useful)
    short_body = body[:200] + "..." if len(body) > 200 else body
    script = (
        f'display notification "{_escape_applescript(short_body)}" '
        f'with title "Broadside" subtitle "{_escape_applescript(title)}"'
    )
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)


def _send_webhook(url: str, subject: str, body: str) -> None:
    payload = {"text": f"*{subject}*\n\n{body}"}
    with httpx.Client(timeout=10) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()


def _send_smtp(config: NotifySmtp, subject: str, body: str) -> None:
    if not config.to:
        return
    msg = MIMEText(body)
    msg["Subject"] = f"Broadside: {subject}"
    msg["From"] = f"broadside@localhost"
    msg["To"] = config.to

    with smtplib.SMTP(config.host, config.port) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.send_message(msg)


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
