#!/usr/bin/env python3
"""
Resource / credential watchdog for the whole automation.

Checks everything the SEO + reel automation depends on and emails an EARLY WARNING
when a key is invalid/expiring or a paid balance is running low — so you can top up
or re-auth before anything actually breaks. Consistent with the "email only when
something needs attention" rule: a fully-healthy check sends NOTHING.

Checks:
  • Anthropic API key      (caption + article generation)     → key valid?
  • Google Drive OAuth     (reel upload + clip/music discovery)→ refresh token valid?
  • Instagram / Graph token(reel posting)                     → valid? expiring soon?
  • DataForSEO balance     (SEO/GEO SERP data)                → money left?
  • Higgsfield key/credits (fallback video generation)        → key set / balance?
  • Gmail SMTP             (how these very warnings are sent)  → login works?

Throttled: the same warning set won't re-send more than every REMONITOR_REPEAT_DAYS
(default 3) days, so you're reminded periodically without daily spam.

Run:  python3 resource_monitor.py           # check + email if anything needs attention
      python3 resource_monitor.py --print    # just print the status table, never email
      python3 resource_monitor.py --force     # email the status even if all OK
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import smtplib
import sys

import requests
from dotenv import load_dotenv

import mailer

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"), override=True)
STATE = os.path.join(BASE, "resource_monitor_state.json")

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def _env(*names, default=""):
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


# ── individual checks: each returns (name, level, detail) ────────────────────

def check_anthropic():
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return ("Anthropic (Captions/Artikel)", FAIL, "ANTHROPIC_API_KEY fehlt in .env")
    try:
        from anthropic import Anthropic
        Anthropic(api_key=key).messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=1,
            messages=[{"role": "user", "content": "ping"}])
        return ("Anthropic (Captions/Artikel)", OK, "Key gültig")
    except Exception as e:
        msg = str(e)
        if "401" in msg or "authentication" in msg.lower() or "invalid" in msg.lower():
            return ("Anthropic (Captions/Artikel)", FAIL, "Key ungültig/abgelaufen — erneuern")
        if "429" in msg or "credit" in msg.lower() or "quota" in msg.lower():
            return ("Anthropic (Captions/Artikel)", WARN, "Rate/Guthaben-Limit — Guthaben prüfen")
        return ("Anthropic (Captions/Artikel)", WARN, f"Check unklar: {msg[:120]}")


def check_google_drive():
    cid  = _env("GOOGLE_DRIVE_CLIENT_ID", "GOOGLE_CLIENT_ID")
    csec = _env("GOOGLE_DRIVE_CLIENT_SECRET", "GOOGLE_CLIENT_SECRET")
    rt   = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN", "")
    if not (cid and csec and rt):
        return ("Google Drive (Reel-Upload/Discovery)", WARN,
                "OAuth nicht vollständig konfiguriert (GOOGLE_DRIVE_REFRESH_TOKEN?)")
    try:
        r = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": cid, "client_secret": csec, "refresh_token": rt,
            "grant_type": "refresh_token"}, timeout=30)
        if r.status_code == 200:
            return ("Google Drive (Reel-Upload/Discovery)", OK, "Token gültig")
        return ("Google Drive (Reel-Upload/Discovery)", FAIL,
                f"Refresh-Token ungültig ({r.json().get('error','?')}) — im OAuth-Playground neu "
                "erzeugen. Tipp: OAuth-App auf 'Production' stellen, sonst laufen Test-Tokens "
                "nach 7 Tagen ab.")
    except Exception as e:
        return ("Google Drive (Reel-Upload/Discovery)", WARN, f"Check fehlgeschlagen: {e}")


def check_instagram():
    tok = os.getenv("IG_ACCESS_TOKEN", "")
    appid, appsec = os.getenv("FB_APP_ID", ""), os.getenv("FB_APP_SECRET", "")
    if not tok:
        return ("Instagram (Reel-Posting)", WARN, "IG_ACCESS_TOKEN fehlt — instagram_auth.py")
    try:
        if appid and appsec:
            r = requests.get("https://graph.facebook.com/debug_token", params={
                "input_token": tok, "access_token": f"{appid}|{appsec}"}, timeout=30).json()
            d = r.get("data", {})
            if not d.get("is_valid"):
                return ("Instagram (Reel-Posting)", FAIL,
                        f"Token ungültig ({d.get('error',{}).get('message','?')}) — neu erzeugen")
            exp = d.get("expires_at", 0)
            if exp and exp > 0:
                days = (exp - datetime.datetime.now().timestamp()) / 86400
                warn_days = int(os.getenv("IG_EXPIRY_WARN_DAYS", "14"))
                if days < warn_days:
                    return ("Instagram (Reel-Posting)", WARN,
                            f"Token läuft in {days:.0f} Tagen ab — rechtzeitig erneuern")
            return ("Instagram (Reel-Posting)", OK, "Token gültig")
        # no app creds → basic validity check
        r = requests.get("https://graph.facebook.com/v21.0/me",
                         params={"access_token": tok}, timeout=30)
        return (("Instagram (Reel-Posting)", OK, "Token gültig") if r.status_code == 200
                else ("Instagram (Reel-Posting)", FAIL, "Token ungültig — neu erzeugen"))
    except Exception as e:
        return ("Instagram (Reel-Posting)", WARN, f"Check fehlgeschlagen: {e}")


def check_dataforseo():
    login, pw = os.getenv("DATAFORSEO_LOGIN", ""), os.getenv("DATAFORSEO_PASSWORD", "")
    if not (login and pw):
        return ("DataForSEO (SERP/GEO)", WARN, "Credentials fehlen (nur SEO-Seite betroffen)")
    try:
        r = requests.get("https://api.dataforseo.com/v3/appendix/user_data",
                         auth=(login, pw), timeout=30).json()
        bal = r["tasks"][0]["result"][0]["money"]["balance"]
        thr = float(os.getenv("DATAFORSEO_MIN_BALANCE", "5"))
        if bal < thr:
            return ("DataForSEO (SERP/GEO)", WARN, f"Guthaben niedrig: ${bal:.2f} (< ${thr:.0f}) — aufladen")
        return ("DataForSEO (SERP/GEO)", OK, f"Guthaben ${bal:.2f}")
    except Exception as e:
        return ("DataForSEO (SERP/GEO)", WARN, f"Guthaben-Check fehlgeschlagen: {e}")


def check_higgsfield():
    key, sec = os.getenv("HIGGSFIELD_API_KEY", ""), os.getenv("HIGGSFIELD_API_SECRET", "")
    if not (key and sec):
        return ("Higgsfield (Fallback-Video)", WARN,
                "Key/Secret fehlt — nur der Video-Fallback betroffen (Drive-Clips laufen weiter)")
    # No documented REST balance endpoint; use HIGGSFIELD_BALANCE_URL if you have one.
    url = os.getenv("HIGGSFIELD_BALANCE_URL", "")
    if url:
        try:
            r = requests.get(url, headers={"hf-api-key": key, "hf-secret": sec}, timeout=30)
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            bal = data.get("balance", data.get("credits"))
            thr = float(os.getenv("HIGGSFIELD_MIN_CREDITS", "20"))
            if isinstance(bal, (int, float)):
                if bal < thr:
                    return ("Higgsfield (Fallback-Video)", WARN, f"Credits niedrig: {bal} (< {thr:.0f}) — aufladen")
                return ("Higgsfield (Fallback-Video)", OK, f"Credits {bal}")
        except Exception as e:
            return ("Higgsfield (Fallback-Video)", WARN, f"Guthaben-Check fehlgeschlagen: {e}")
    return ("Higgsfield (Fallback-Video)", OK, "Key gesetzt (Guthaben nur im Dashboard/MCP sichtbar)")


def check_gmail():
    sender = os.getenv("EMAIL_FROM", "")
    pw = os.getenv("EMAIL_APP_PASS", "").replace(" ", "")
    if not (sender and pw):
        return ("Gmail (Warn-Mails)", FAIL, "EMAIL_FROM / EMAIL_APP_PASS fehlt — Warnungen kämen nicht an")
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls()
            s.login(sender, pw)
        return ("Gmail (Warn-Mails)", OK, "SMTP-Login ok")
    except Exception as e:
        return ("Gmail (Warn-Mails)", FAIL, f"SMTP-Login fehlgeschlagen: {e}")


CHECKS = [check_anthropic, check_google_drive, check_instagram,
          check_dataforseo, check_higgsfield, check_gmail]


def _should_email(signature: str) -> bool:
    """Throttle: same warning set re-sends at most every REMONITOR_REPEAT_DAYS days."""
    repeat = int(os.getenv("REMONITOR_REPEAT_DAYS", "3"))
    today = datetime.date.today()
    try:
        st = json.load(open(STATE))
        if st.get("last_sig") == signature:
            last = datetime.date.fromisoformat(st.get("last_sent", "2000-01-01"))
            if (today - last).days < repeat:
                return False
    except Exception:
        pass
    return True


def _save_state(signature: str):
    try:
        json.dump({"last_sig": signature, "last_sent": datetime.date.today().isoformat()},
                  open(STATE, "w"), indent=2)
    except Exception:
        pass


def main():
    results = []
    for fn in CHECKS:
        try:
            results.append(fn())
        except Exception as e:
            results.append((fn.__name__, WARN, f"Check-Fehler: {e}"))

    icon = {OK: "✅", WARN: "⚠️", FAIL: "❌"}
    lines = [f"{icon[lvl]} {name}: {detail}" for name, lvl, detail in results]
    print("\n".join(lines))

    attention = [r for r in results if r[1] in (WARN, FAIL)]
    force = "--force" in sys.argv
    if "--print" in sys.argv:
        return

    if not attention and not force:
        return  # all healthy → stay silent

    signature = hashlib.sha1(
        "|".join(f"{n}:{l}" for n, l, _ in sorted(attention)).encode()).hexdigest()
    if attention and not force and not _should_email(signature):
        print("   (Warnung bereits kürzlich gemeldet — throttled, keine erneute Mail.)")
        return

    fails = [r for r in attention if r[1] == FAIL]
    subj = ("❌ Velluto Automation — HANDLUNG NÖTIG" if fails
            else "⚠️ Velluto Automation — bald nachladen/erneuern") if attention else \
           "✅ Velluto Automation — alles ok"
    body = ("Ressourcen-Check der Automation:\n\n" + "\n".join(lines) +
            "\n\nNur WARN/❌-Punkte brauchen Handlung. Diese Mail kommt nur, wenn etwas "
            "Aufmerksamkeit braucht (throttled auf alle paar Tage).")
    mailer.send_email(subj, body)
    if attention:
        _save_state(signature)


if __name__ == "__main__":
    main()
