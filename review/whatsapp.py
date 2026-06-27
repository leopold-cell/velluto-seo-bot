"""
Report delivery — EMAIL ONLY.

Per Leopold: all reporting goes via e-mail, using the same Gmail mechanism as the
Instagram bot (EMAIL_FROM / EMAIL_APP_PASS / EMAIL_TO via the shared `mailer`).
The previous WhatsApp/Telegram channels were removed. The module/function names
are kept so existing callers (blog_review.py) don't change.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mailer


def deliver(text: str, subject: str = "Velluto Report", email_body: str | None = None) -> str:
    """Email the report (full `email_body` if given, else `text`). Returns the
    channel used: "email" on success, else "none"."""
    ok = mailer.send_email(subject, email_body or text)
    return "email" if ok else "none"
