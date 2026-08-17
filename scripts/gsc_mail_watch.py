#!/usr/bin/env python3
"""
Weekly Search Console mail watch — read the alerts, then VERIFY them live.

Google mails an alert when it detects a problem. By the time anyone reads it the
alert is often already stale: the 404 report from 2026-07-28 named URLs that the
legal repair brought back days later, and the "fix failed" mail from 2026-08-07
referred to pages that resolve fine today. Acting on the mail alone means fixing
things that are no longer broken.

So this does not trust the mail. For every alert it re-checks the live site and
says which of three states applies:

  RESOLVED   the site no longer shows the problem → request validation in GSC
  OPEN       still reproducible → names the repair script that handles it
  MANUAL     Google's suggestion should NOT be auto-applied (see below)

WHY IT DOES NOT AUTO-FIX EVERYTHING
The two most recent alerts are the argument. The "Produkt-Snippets" one asks for
review/aggregateRating fields — on products that already have them, from a stale
crawl. An eager fixer would have "added" the missing fields, and on a product
with no genuine reviews that is a fabricated rating: § 5 UWG and the EU
fake-review ban, the exact class of problem this repo spent a week removing.
Some Google suggestions must be declined. That is a judgement, so it is reported,
not executed.

Mechanical, verifiable repairs are named with the script that performs them; they
stay one command away rather than running unattended against live content.

Reads via IMAP with the credentials mailer.py already uses (EMAIL_FROM /
EMAIL_APP_PASS) — no new access. Read-only on the mailbox: nothing is marked,
moved or deleted.

Usage:
  python3 scripts/gsc_mail_watch.py            # gated weekly
  python3 scripts/gsc_mail_watch.py --force
  python3 scripts/gsc_mail_watch.py --days 30
"""
import datetime as dt
import email
import email.header
import imaplib
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"), override=True)

HISTORY = os.path.join(ROOT, "data", "gsc_mail_watch.json")
SENDER = "sc-noreply@google.com"
DOMAIN = "velluto-shop.com"          # the account also receives mail for other properties
GATE_DAYS = 7
DAYS = 14
if "--days" in sys.argv:
    i = sys.argv.index("--days")
    if i + 1 < len(sys.argv):
        DAYS = max(1, int(sys.argv[i + 1]))

# Google's WNC-xxxx message-type codes are stable, so they classify far more
# reliably than the localised subject line (this account receives German).
ALERTS = {
    "WNC-10030322": ("Produkt-Snippets (strukturierte Daten)", "structured_data"),
    "WNC-10031170": ("Fehlerbehebung fehlgeschlagen", "fix_failed"),
    "WNC-10009381": ("Neue Nicht-Indexierungs-Gründe", "indexing"),
    "WNC-10009382": ("Nicht-Indexierung in einer Sitemap", "indexing"),
}
# Subject fragments as a fallback when no code is present.
SUBJECT_HINTS = [
    (r"produkt-snippets|structured data|strukturierte daten", "structured_data"),
    (r"fehlgeschlagen|failed", "fix_failed"),
    (r"nicht indexiert|not indexed|indexierung", "indexing"),
    (r"meilenstein|glückwunsch|congratulations|leistung|performance", "noise"),
]


def _decode(raw) -> str:
    if not raw:
        return ""
    out = []
    for part, enc in email.header.decode_header(raw):
        out.append(part.decode(enc or "utf-8", "ignore") if isinstance(part, bytes) else part)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _body(msg) -> str:
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() == "text/plain":
                try:
                    return p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "ignore")
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "ignore")
    except Exception:
        return ""


def fetch_alerts(days: int) -> list[dict]:
    user = os.getenv("EMAIL_FROM", "")
    pw = os.getenv("EMAIL_APP_PASS", "").replace(" ", "")
    if not user or not pw:
        print("   GSC mail watch: EMAIL_FROM / EMAIL_APP_PASS missing — skipping")
        return []
    since = (dt.date.today() - dt.timedelta(days=days)).strftime("%d-%b-%Y")
    out = []
    try:
        m = imaplib.IMAP4_SSL("imap.gmail.com")
        m.login(user, pw)
        m.select("INBOX", readonly=True)      # readonly: never touch the mailbox
        typ, data = m.search(None, f'(FROM "{SENDER}" SINCE {since})')
        for num in (data[0].split() if typ == "OK" else []):
            typ, raw = m.fetch(num, "(RFC822)")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(raw[0][1])
            subject, body = _decode(msg.get("Subject")), _body(msg)
            blob = f"{subject} {body}"
            # The mailbox also carries alerts for other properties.
            if DOMAIN not in blob:
                continue
            code = (re.search(r"WNC-\d+", blob) or [None])[0] if re.search(r"WNC-\d+", blob) else None
            kind = ALERTS.get(code, (None, None))[1]
            if not kind:
                for pat, k in SUBJECT_HINTS:
                    if re.search(pat, subject, re.I):
                        kind = k
                        break
            out.append({"date": _decode(msg.get("Date"))[:16], "subject": subject[:110],
                        "code": code, "kind": kind or "unknown"})
        m.logout()
    except Exception as e:
        print(f"   ⚠️  GSC mail watch: IMAP failed: {e}")
    return out


def _get(url: str) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Velluto-gsc-watch/1.0"})
        r = urllib.request.urlopen(req, timeout=20)
        return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def verify(kind: str) -> tuple[str, str]:
    """(state, note) — RESOLVED / OPEN / MANUAL, checked against the live site."""
    if kind == "noise":
        return "IGNORE", "Meilenstein-/Leistungsmail, kein Problem"

    if kind == "indexing":
        code, xml = _get(f"https://{DOMAIN}/sitemap_blogs_1.xml")
        urls = re.findall(r"<loc>([^<]+)</loc>", xml)[:40]
        bad = [u for u in urls if _get(u)[0] not in (200, 301, 302)]
        if bad:
            return "OPEN", (f"{len(bad)} von {len(urls)} Sitemap-URLs antworten nicht: "
                            f"{bad[0].rsplit('/', 1)[-1]} … "
                            f"→ scripts/scrub_drafted_links.py --sitemap-only")
        return "RESOLVED", (f"alle {len(urls)} geprüften Sitemap-URLs liefern 200/301 — "
                            "in der GSC 'Behebung validieren' klicken")

    if kind == "structured_data":
        # The product sitemap carries ?from=&to= parameters, so it cannot be
        # guessed — resolve it from the index. Guessing returned an empty list,
        # and "0 of 0 products are fine" reported RESOLVED: a false all-clear,
        # which is worse than an error.
        _, index = _get(f"https://{DOMAIN}/sitemap.xml")
        sm = next((u for u in re.findall(r"<loc>([^<]+)</loc>", index)
                   if "sitemap_products" in u), "")
        prods = [u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", _get(sm)[1])
                 if u.strip().startswith("http")][:20] if sm else []
        if not prods:
            return "OPEN", "Produkt-Sitemap nicht lesbar — Prüfung nicht möglich"
        missing = []
        for u in prods:
            _, html = _get(u)
            if html and ("aggregateRating" not in html or '"review"' not in html):
                missing.append(u.rsplit("/", 1)[-1])
        if not missing:
            return "RESOLVED", (f"alle {len(prods)} Produkte führen review + aggregateRating — "
                                "die Meldung stammt aus einem älteren Crawl; validieren")
        return "MANUAL", (f"{len(missing)} Produkt(e) ohne Bewertungsfelder: {', '.join(missing[:3])}. "
                          "NICHT automatisch ergänzen — ein erfundenes Rating verstößt gegen "
                          "§ 5 UWG und das EU-Fake-Review-Verbot. Nur eintragen, wenn es echte "
                          "Rezensionen gibt; sonst ist das Weglassen korrekt und die Warnung "
                          "bleibt bewusst stehen.")

    if kind == "fix_failed":
        return "OPEN", ("Eine beantragte Validierung ist fehlgeschlagen. Häufigste Ursache: "
                        "sie lief, bevor die Reparatur live war. Zustand oben prüfen und "
                        "gegebenenfalls neu beantragen.")
    return "OPEN", "unbekannter Alert-Typ — manuell ansehen"


def main() -> None:
    hist = []
    try:
        with open(HISTORY, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        pass
    if "--force" not in sys.argv and hist:
        try:
            last = dt.date.fromisoformat(hist[-1]["date"])
            if (dt.date.today() - last).days < GATE_DAYS:
                print("   GSC mail watch: geprüft vor <7 Tagen — nichts zu tun")
                return
        except Exception:
            pass

    alerts = fetch_alerts(DAYS)
    print(f"📬 GSC-Mails der letzten {DAYS} Tage: {len(alerts)}")
    if not alerts:
        return

    seen, findings = set(), []
    for a in alerts:
        if a["kind"] in seen:          # one verification per problem class is enough
            continue
        seen.add(a["kind"])
        state, note = verify(a["kind"])
        findings.append({**a, "state": state, "note": note})
        icon = {"RESOLVED": "✅", "OPEN": "⚠️", "MANUAL": "✋", "IGNORE": "·"}[state]
        print(f"\n  {icon} {state}  {ALERTS.get(a['code'], (a['kind'],))[0]}")
        print(f"     {a['subject'][:88]}")
        print(f"     {note}")

    entry = {"date": dt.date.today().isoformat(), "alerts": len(alerts),
             "findings": [f for f in findings if f["state"] in ("OPEN", "MANUAL")]}
    hist.append(entry)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist[-52:], f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
