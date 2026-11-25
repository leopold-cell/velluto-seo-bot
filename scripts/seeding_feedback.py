#!/usr/bin/env python3
"""
Read feedback the operator sends by REPLYING to the weekly "Velluto Seeding-Ziele" mail.

The mail goes from the bot's mailbox to the operator's own address, so a reply lands in
the same inbox; nothing read it until now. This reads those replies (IMAP, read-only:
nothing is marked, moved or deleted, same access gsc_mail_watch.py already uses) and
turns one-line commands into data/seeding_feedback.json, which seeding_targets.py applies
to the next list:

  skip   <domain>    never show again
  done   <domain>    contacted / handled: listed under "Schon kontaktiert", not as a target
  später <domain>    hide for 30 days
  reset  <domain>    undo skip / done / später

Anything else in the reply is kept as a free-text note (read by Claude from the repo).
Only mail FROM the operator's own address, with "Seeding-Ziele" in the subject, counts;
quoted text and signatures are ignored; only the verbs above are interpreted.

Usage:
  python3 scripts/seeding_feedback.py            # daily step, idempotent
"""
import datetime as dt
import email
import email.header
import email.utils
import imaplib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "data", "seeding_feedback.json")
SUBJECT_KEY = "seeding-ziele"
LATER_DAYS = 30
DAYS_BACK = 21
MAX_NOTES = 40

_VERBS = {"skip": "skip", "raus": "skip", "nein": "skip",
          "done": "done", "erledigt": "done", "kontaktiert": "done",
          "später": "later", "spaeter": "later", "later": "later",
          "reset": "reset", "zurück": "reset", "zurueck": "reset"}
_DOMAIN = re.compile(r"^(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9.-]*\.[a-z]{2,})(?:[/?#].*)?$", re.I)
_QUOTE_START = re.compile(r"^(am .+ schrieb|on .+ wrote|-{2,}\s*(original|ursprüngliche)|von:|from:|gesendet von)",
                          re.I)


def parse_reply(body: str) -> tuple[list[tuple[str, str]], list[str]]:
    """([(verb, domain)], [free-text lines]) from one reply body. Stops at the quoted mail."""
    cmds, notes = [], []
    for raw in (body or "").splitlines():
        line = raw.strip()
        if _QUOTE_START.match(line):
            break
        if not line or line.startswith(">"):
            continue
        parts = line.split(None, 2)
        verb = _VERBS.get(parts[0].lower().rstrip(":")) if parts else None
        m = _DOMAIN.match(parts[1].strip(",.;")) if verb and len(parts) > 1 else None
        if verb and m:
            cmds.append((verb, m.group(1).lower()))
        else:
            notes.append(line[:300])
    return cmds, notes


def apply(state: dict, cmds: list[tuple[str, str]], today: dt.date) -> None:
    skip, done, later = set(state["skip"]), state["done"], state["later"]
    for verb, d in cmds:
        if verb == "skip":
            skip.add(d)
        elif verb == "done":
            done[d] = today.isoformat()
        elif verb == "later":
            later[d] = (today + dt.timedelta(days=LATER_DAYS)).isoformat()
        elif verb == "reset":
            skip.discard(d)
            done.pop(d, None)
            later.pop(d, None)
    state["skip"] = sorted(skip)


def _decode(raw) -> str:
    out = []
    for part, enc in email.header.decode_header(raw or ""):
        out.append(part.decode(enc or "utf-8", "ignore") if isinstance(part, bytes) else part)
    return "".join(out)


def _text(msg) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    for p in parts:
        if p.get_content_type() == "text/plain":
            try:
                return p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "ignore")
            except Exception:
                continue
    return ""


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
    user = os.getenv("EMAIL_FROM", "")
    pw = os.getenv("EMAIL_APP_PASS", "").replace(" ", "")
    if not user or not pw:
        print("   Seeding-Feedback: EMAIL_FROM / EMAIL_APP_PASS fehlen — übersprungen")
        return
    try:
        state = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        state = {}
    for k, v in (("skip", []), ("done", {}), ("later", {}), ("notes", []), ("processed", [])):
        state.setdefault(k, v)
    mine = {a.lower() for a in (user, os.getenv("EMAIL_TO", "leopold@velluto-brand.com")) if a}
    since = (dt.date.today() - dt.timedelta(days=DAYS_BACK)).strftime("%d-%b-%Y")
    new = 0
    try:
        m = imaplib.IMAP4_SSL("imap.gmail.com")
        m.login(user, pw)
        m.select("INBOX", readonly=True)
        typ, data = m.search(None, f'(SINCE {since} SUBJECT "Seeding-Ziele")')
        for num in (data[0].split() if typ == "OK" else []):
            typ, raw = m.fetch(num, "(RFC822)")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(raw[0][1])
            mid = (msg.get("Message-ID") or "").strip()
            subj = _decode(msg.get("Subject")).lower()
            sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
            # Only REPLIES from the operator: the bot's own digest has the same From.
            if not subj.startswith(("re:", "aw:")) or SUBJECT_KEY not in subj \
                    or sender not in mine or mid in state["processed"]:
                continue
            cmds, notes = parse_reply(_text(msg))
            apply(state, cmds, dt.date.today())
            for n in notes:
                state["notes"].append({"date": dt.date.today().isoformat(), "text": n})
            state["processed"].append(mid)
            new += 1
            print(f"   Seeding-Feedback: {len(cmds)} Befehl(e), {len(notes)} Notiz(en) aus einer Antwort")
        m.logout()
    except Exception as e:
        print(f"   Seeding-Feedback: Postfach nicht lesbar ({str(e)[:80]}) — übersprungen")
        return
    state["notes"] = state["notes"][-MAX_NOTES:]
    state["processed"] = state["processed"][-200:]
    if new:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump(state, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    else:
        print("   Seeding-Feedback: keine neuen Antworten")


if __name__ == "__main__":
    main()
