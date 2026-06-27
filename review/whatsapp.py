"""
Report delivery. deliver() sends the report by EMAIL (if SMTP is configured) AND
via WhatsApp → Telegram fallback, so the 28-day audit lands in the inbox while the
short push still goes to chat. Each channel is independent and degrades to a no-op
when its credentials are absent.

Env (set as secrets on the VPS/CI):
  Email (full report → inbox):
    SMTP_HOST          — e.g. smtp.gmail.com / smtp.your-host.de
    SMTP_PORT          — 587 (STARTTLS, default) or 465 (SSL)
    SMTP_USER          — SMTP login
    SMTP_PASS          — SMTP password / app-password
    REPORT_EMAIL_TO    — recipient(s), comma-separated (default leopold@velluto-shop.com)
    REPORT_EMAIL_FROM  — sender address (default = SMTP_USER)
  WhatsApp (short push):
    WHATSAPP_TOKEN / WHATSAPP_PHONE_ID / WHATSAPP_TO / WHATSAPP_TEMPLATE (optional)
  Telegram fallback: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (via seo_bot.notify)

Note: Meta only allows free-form text within 24h of the recipient's last message;
otherwise an approved template is required. The Telegram fallback guarantees the
short report is always delivered; email guarantees the full report is archived.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def _send_email(text: str, subject: str) -> bool:
    """Send the report by email via SMTP. No-op (returns False) if unconfigured."""
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    pw   = os.getenv("SMTP_PASS")
    to   = os.getenv("REPORT_EMAIL_TO", "leopold@velluto-shop.com")
    if not (host and user and pw and to):
        return False
    port   = int(os.getenv("SMTP_PORT", "587"))
    sender = os.getenv("REPORT_EMAIL_FROM", user)
    recipients = [a.strip() for a in to.split(",") if a.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    msg.set_content(text)
    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(user, pw)
                s.send_message(msg)
        return True
    except Exception as e:
        print(f"   ⚠️  email: {e}")
        return False


def _send_whatsapp(text: str) -> bool:
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_ID")
    to = os.getenv("WHATSAPP_TO")
    if not (token and phone_id and to):
        return False
    template = os.getenv("WHATSAPP_TEMPLATE")
    url = f"{GRAPH}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if template:
        payload = {
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": template, "language": {"code": "en"},
                         "components": [{"type": "body",
                                         "parameters": [{"type": "text", "text": text[:1000]}]}]},
        }
    else:
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text",
                   "text": {"body": text[:4000]}}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code < 300:
            return True
        print(f"   ⚠️  whatsapp: HTTP {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        print(f"   ⚠️  whatsapp: {e}")
        return False


def _send_telegram(text: str) -> bool:
    try:
        import seo_bot
        seo_bot.notify(text)
        return bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    except Exception:
        return False


def deliver(text: str, subject: str = "Velluto Report", email_body: str | None = None) -> str:
    """Deliver the report. Emails the full report (email_body or text) when SMTP is
    configured, AND sends the short `text` to WhatsApp → Telegram. Returns the
    channel(s) used, e.g. "email+whatsapp"."""
    channels: list[str] = []
    if _send_email(email_body or text, subject):
        channels.append("email")
    if _send_whatsapp(text):
        channels.append("whatsapp")
    elif _send_telegram(text):
        channels.append("telegram(fallback)")
    return "+".join(channels) if channels else "none"
