"""
Shared email sender — same mechanism the Instagram bot uses (Gmail SMTP, STARTTLS)
so a single set of .env vars covers both bots:

  EMAIL_FROM      — Gmail sender address
  EMAIL_APP_PASS  — Gmail App-Password (myaccount.google.com/apppasswords)
  EMAIL_TO        — recipient (default leopold@velluto-brand.com)

No-op (returns False, logs a skip) when EMAIL_FROM / EMAIL_APP_PASS are unset, so
importing/calling this never breaks the pipeline.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)


def send_email(subject: str, body: str, to: str | None = None) -> bool:
    """Send a plain-text email via Gmail SMTP. Returns True on success."""
    sender = os.getenv("EMAIL_FROM", "")
    app_pw = os.getenv("EMAIL_APP_PASS", "")
    to     = to or os.getenv("EMAIL_TO", "leopold@velluto-brand.com")
    if not sender or not app_pw:
        print("   ✉ email skip — EMAIL_FROM / EMAIL_APP_PASS not set in .env")
        return False
    try:
        msg = MIMEText(body, _charset="utf-8")
        msg["Subject"] = subject
        msg["From"]    = sender
        msg["To"]      = to
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls()
            s.login(sender, app_pw)
            s.send_message(msg)
        print(f"   ✉ email sent to {to}: {subject}")
        return True
    except Exception as e:
        print(f"   ⚠️  email failed: {e}")
        return False
