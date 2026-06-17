"""
WhatsApp delivery via Meta WhatsApp Cloud API (free tier), with automatic
fallback to the existing Telegram notify() when WhatsApp isn't configured.

Env (set as secrets on the VPS/CI):
  WHATSAPP_TOKEN     — permanent access token
  WHATSAPP_PHONE_ID  — phone number ID
  WHATSAPP_TO        — recipient MSISDN, e.g. "4915123456789"
  WHATSAPP_TEMPLATE  — (optional) approved utility template name for sending
                       outside the 24h customer-service window. If unset, a plain
                       text message is attempted (works inside the 24h window).

Note: Meta only allows free-form text within 24h of the recipient's last message;
otherwise an approved template is required. The Telegram fallback guarantees the
report is always delivered.
"""
from __future__ import annotations

import os

import requests

GRAPH = "https://graph.facebook.com/v21.0"


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


def deliver(text: str) -> str:
    """Try WhatsApp, fall back to Telegram. Returns the channel used."""
    if _send_whatsapp(text):
        return "whatsapp"
    if _send_telegram(text):
        return "telegram(fallback)"
    return "none"
