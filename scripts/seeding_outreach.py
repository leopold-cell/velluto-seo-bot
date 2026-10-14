#!/usr/bin/env python3
"""
Seeding outreach — turns data/seeding_targets.json into ready-to-send pitches.

seeding_targets.py answers WHO (the sites AI cites instead of Velluto). This answers
WHAT TO SAY to each of them, so the only manual step left is pressing send.

WHAT IT DOES, per target (editorial / YouTube / stockist), in the target's language:
  · finds the page that matters: the roundup that already ranks for our keywords,
    and the site's contact / tips page (public web search, no scraping of the site)
  · writes a short pitch grounded in specs we can evidence, offering a free sample
    with NO strings attached and no promise of coverage
  · runs it through check_compliance + check_brand_facts, like every other
    user-visible text in this repo (docs/LEGAL_GUARDRAILS.md)
  · remembers who was pitched, so nobody is mailed twice within 45 days, and lists
    pitches that are due a follow-up after 14 days

WHY IT DOES NOT SEND
  A cold mail goes out under the Velluto name to a person who did not ask for it.
  One wrong claim or one badly aimed pitch to Cycling Weekly costs the relationship
  for good, and a sent mail cannot be recalled. So the bot does the work of five
  hours — research, drafting, fact-check, tracking — and delivers one mail with
  everything pasted in. Auto-sending can be added later for contacts the owner has
  verified; it should be an allowlist, not a default.

Usage:
  python3 scripts/seeding_outreach.py            # gated weekly
  python3 scripts/seeding_outreach.py --force
  python3 scripts/seeding_outreach.py --count 3  # fewer pitches per run
"""
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"), override=True)

TARGETS = os.path.join(ROOT, "data", "seeding_targets.json")
STATE = os.path.join(ROOT, "data", "seeding_outreach_state.json")
OUT = os.path.join(ROOT, "output", "seeding_outreach.txt")

DEFAULT_COUNT = 5
RESEND_AFTER_DAYS = 45      # never re-pitch the same domain sooner
FOLLOW_UP_AFTER_DAYS = 14   # one polite nudge, listed in the digest
GATE_DAYS = 7

LANG_NAME = {"en": "English", "de": "German", "nl": "Dutch", "fr": "French"}
TLD_LANG = {"de": "de", "at": "de", "ch": "de", "nl": "nl", "be": "nl", "fr": "fr"}

# Facts the pitch may state. Same list reddit_daily uses; if a spec changes, change
# it in both places (or, better, move it to config — not done here to keep this
# script independent of a refactor). The StradaPro is NOT photochromic or mirrored
# (that is the Chromo) and no Velluto product is polarised or prescription.
FACTS = ("25 g, UV400-certified, tool-free interchangeable lenses, built-in "
         "anti-fog, 30-day trial, from 69 EUR")

PROMPT = """You write a short first-contact email from Velluto (a cycling-eyewear brand,
velluto-shop.com) to {kind_desc}.
Write in {language}. Sign as "the Velluto team". Plain text, no markdown.

Recipient: {domain}
{page_line}
Why we are writing: {angle}

Rules, all of them binding:
- 90-130 words. First sentence says who we are and why THIS site, in one line.
- Offer to send the Velluto StradaPro ({facts}) for free. Say explicitly that there
  is no obligation to cover it and no say in the verdict.
- State only the specs listed above. Never call the StradaPro photochromic,
  mirrored, polarised or prescription. No test result, ranking, award or review
  quote — we have none to cite.
- No superiority claim over any named brand, no "best", no "better than".
- No flattery about their site and no invented detail about their readers.
- Ask one concrete thing: the postal address and whether they would like a sample.
- No placeholders in square brackets: the text must be sendable exactly as written.

Output EXACTLY:
SUBJECT: <subject line, max 60 chars>
BODY:
<email body>"""

KIND = {
    "editorial": ("an editor or gear tester at a cycling publication",
                  "Your roundup already ranks for {kw}; a reader comparing options should "
                  "be able to see a lightweight, interchangeable-lens pair at a lower price."),
    "youtube":   ("a cycling YouTube creator",
                  "Your videos rank for {kw}; offering a sample for an honest look."),
    "retailer":  ("the buyer or category manager of a cycling retailer",
                  "You list cycling eyewear that ranks for {kw}; we would like to discuss "
                  "stocking the StradaPro. Ask for wholesale terms and listing requirements."),
}


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _gate_ok(force: bool) -> bool:
    if force:
        return True
    last = _load(STATE, {}).get("_last_run")
    if not last:
        return True
    try:
        return (dt.date.today() - dt.date.fromisoformat(last)).days >= GATE_DAYS
    except Exception:
        return True


def _lang_for(domain: str) -> str:
    return TLD_LANG.get(domain.rsplit(".", 1)[-1], "en")


_CONTACT_HINT = re.compile(r"contact|kontakt|contacto|contact-us|get-in-touch|about|"
                           r"write-for-us|tips|redaktion|impressum|partner|advertis", re.I)


def _find_pages(domain: str, keyword: str) -> tuple[str, str]:
    """(roundup_url, contact_url), each "" when not found. Public search only."""
    try:
        from ddgs import DDGS
    except ImportError:
        return "", f"https://{domain}"
    roundup = contact = ""
    try:
        with DDGS() as d:
            if keyword:
                for hit in d.text(f"site:{domain} {keyword}", max_results=3):
                    u = hit.get("href") or hit.get("url") or ""
                    if domain in u:
                        roundup = u
                        break
            for hit in d.text(f"site:{domain} contact OR kontakt OR 'get in touch'",
                              max_results=6):
                u = hit.get("href") or hit.get("url") or ""
                if domain in u and _CONTACT_HINT.search(u):
                    contact = u
                    break
    except Exception as e:
        print(f"   ⚠️  page search failed for {domain}: {e}")
    return roundup, contact or f"https://{domain}"


def _youtube_videos(keywords: list[str], state: dict, limit: int) -> list[dict]:
    """youtube.com is a platform, not a recipient. The people to write to are the
    creators whose videos rank for our keywords, so this finds those videos and
    returns one pseudo-target per creator (the video URL is the key in the state
    file). No creators found means no YouTube pitch this week — a mail addressed to
    "youtube.com" would be worthless."""
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    out, seen = [], set()
    try:
        with DDGS() as d:
            for kw in keywords[:3]:
                for hit in d.text(f"site:youtube.com {kw}", max_results=6):
                    url = (hit.get("href") or hit.get("url") or "").split("&")[0]
                    if "youtube.com/watch" not in url or url in seen or url in state:
                        continue
                    seen.add(url)
                    out.append({"domain": url, "title": (hit.get("title") or "")[:90],
                                "keywords": [kw], "score": 0,
                                "ai_cited_velluto_absent": 1})
                    if len(out) >= limit:
                        return out
    except Exception as e:
        print(f"   ⚠️  youtube search failed: {e}")
    return out


_AUTH_DEAD = False


def _write(target: dict, kind: str, lang: str, roundup: str) -> tuple[str, str, str]:
    """(subject, body, note). Falls back to a skeleton without an API key."""
    global _AUTH_DEAD
    kw = (target.get("keywords") or ["cycling sunglasses"])[0]
    kind_desc, angle = KIND[kind]
    key = os.getenv("ANTHROPIC_API_KEY", "")
    skeleton_subj = f"Velluto StradaPro — sample for {target['domain']}"
    if not key or _AUTH_DEAD:
        return (skeleton_subj,
                "[Rohentwurf — kein gültiger ANTHROPIC_API_KEY]\n"
                f"Empfänger: {target['domain']} ({kind}), Sprache: {LANG_NAME[lang]}\n"
                f"Aufbau: wer wir sind → warum diese Seite ({kw}) → kostenloses Muster "
                f"ohne Verpflichtung → Postadresse erfragen.\nSpecs: {FACTS}",
                "Rohentwurf")
    prompt = PROMPT.format(
        kind_desc=kind_desc, language=LANG_NAME[lang], domain=target["domain"],
        page_line=(f"Their page: {roundup}" if roundup
                   else f"Their video: {target['domain']} — {target.get('title', '')}"
                   if kind == "youtube" else ""),
        angle=angle.format(kw=kw), facts=FACTS)
    try:
        from anthropic import Anthropic
        r = Anthropic(api_key=key).messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=500,
            messages=[{"role": "user", "content": prompt}])
        raw = r.content[0].text.strip()
        s = re.search(r"SUBJECT:\s*(.+)", raw)
        b = re.search(r"BODY:\s*([\s\S]+)", raw)
        return (s.group(1).strip() if s else skeleton_subj,
                b.group(1).strip() if b else raw, "")
    except Exception as e:
        msg = str(e)
        if "authentication" in msg.lower() or "401" in msg:
            _AUTH_DEAD = True
            return _write(target, kind, lang, roundup)
        return skeleton_subj, f"[Rohentwurf — Entwurf fehlgeschlagen: {msg[:90]}]", "Rohentwurf"


def _issues(subject: str, body: str) -> list[str]:
    try:
        from briefs.quality_gate import check_compliance, check_brand_facts
    except Exception:
        return ["Legal-Gate nicht ladbar — nicht senden, bevor geprüft"]
    post = {"title": subject, "body_html": body}
    return list(check_compliance(post)) + list(check_brand_facts(post))


def _pick_targets(data: dict, state: dict, count: int) -> list[tuple[dict, str]]:
    today = dt.date.today()
    picks = []
    pool = ([(t, t["type"]) for t in data.get("seeding", []) if t["type"] in ("editorial", "youtube")]
            + [(t, "retailer") for t in data.get("stockist", [])])
    pool.sort(key=lambda p: -p[0]["score"])
    for t, kind in pool:
        prev = state.get(t["domain"])
        if prev:
            try:
                age = (today - dt.date.fromisoformat(prev["drafted"])).days
            except Exception:
                age = 0
            if age < RESEND_AFTER_DAYS:
                continue
        picks.append((t, kind))
        if len(picks) >= count:
            break
    return picks


def _follow_ups(state: dict) -> list[str]:
    today = dt.date.today()
    due = []
    for dom, rec in state.items():
        if dom.startswith("_") or rec.get("followed_up") or rec.get("replied"):
            continue
        try:
            age = (today - dt.date.fromisoformat(rec["drafted"])).days
        except Exception:
            continue
        if FOLLOW_UP_AFTER_DAYS <= age < RESEND_AFTER_DAYS:
            due.append(f"{dom} (Entwurf vor {age} Tagen)")
    return due


def build(count: int) -> tuple[list[dict], list[str]]:
    data = _load(TARGETS, {})
    state = _load(STATE, {})
    items = []
    picks = _pick_targets(data, state, count)
    expanded = []
    for t, kind in picks:
        if kind == "youtube":
            vids = _youtube_videos(t.get("keywords") or [], state, 2)
            expanded += [(v, "youtube") for v in vids]
        else:
            expanded.append((t, kind))
    for t, kind in expanded:
        is_video = kind == "youtube"
        lang = "en" if is_video else _lang_for(t["domain"])
        kw = (t.get("keywords") or [""])[0]
        roundup, contact = (("", t["domain"] + "  (Kanal → Info → Geschäftliche Anfragen)")
                            if is_video else _find_pages(t["domain"], kw))
        subject, body, note = _write(t, kind, lang, roundup)
        issues = _issues(subject, body)
        items.append({"domain": t["domain"], "kind": kind, "lang": lang, "score": t["score"],
                      "ai_gap": bool(t.get("ai_cited_velluto_absent")),
                      "roundup": roundup, "contact": contact,
                      "subject": subject, "body": body, "issues": issues, "note": note})
    return items, _follow_ups(state)


def render(items: list[dict], due: list[str]) -> str:
    if not items and not due:
        return ("Seeding-Outreach: nichts zu tun — keine neuen Ziele "
                f"(alle innerhalb {RESEND_AFTER_DAYS} Tagen schon angeschrieben) "
                "oder data/seeding_targets.json fehlt.")
    L = [f"Seeding-Outreach — {len(items)} Entwürfe. Nichts wurde gesendet.", "",
         "Vorgehen: Kontaktseite öffnen → Betreff und Text einfügen → senden. "
         "Entwürfe mit ⛔ nicht senden.", ""]
    for i, it in enumerate(items, 1):
        gap = "  🤖 KI zitiert sie, uns nicht" if it["ai_gap"] else ""
        L.append(f"── #{i}  {it['domain']}  [{it['kind']} · {it['lang'].upper()} · "
                 f"Score {it['score']}]{gap}")
        L.append(f"   Kontakt:  {it['contact']}")
        if it["roundup"]:
            L.append(f"   Bezug:    {it['roundup']}")
        if it["issues"]:
            L.append("   ⛔ NICHT SENDEN — Legal-/Fakten-Gate:")
            for x in it["issues"]:
                L.append(f"      {x[:120]}")
        if it["note"]:
            L.append(f"   ⚠️  {it['note']}")
        L.append(f"   Betreff:  {it['subject']}")
        L.append("   Text:")
        for line in it["body"].splitlines():
            L.append(f"      {line}")
        L.append("")
    if due:
        L.append("Nachfassen fällig (eine kurze Erinnerung, danach nicht mehr):")
        L += [f"   • {d}" for d in due]
    return "\n".join(L).rstrip()


def _save_state(items: list[dict]) -> None:
    state = _load(STATE, {})
    today = dt.date.today().isoformat()
    for it in items:
        if it["issues"] or it["note"]:
            continue        # a blocked or skeleton draft was not actually usable — retry next week
        state[it["domain"]] = {"drafted": today, "kind": it["kind"]}
    state["_last_run"] = today
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def _int_arg(flag: str, default: int) -> int:
    if flag not in sys.argv:
        return default
    i = sys.argv.index(flag)
    try:
        return max(1, int(sys.argv[i + 1].strip().rstrip(".,;")))
    except (IndexError, ValueError):
        print(f"   ⚠️  {flag} expects a number — using {default}")
        return default


def main() -> None:
    if not _gate_ok("--force" in sys.argv):
        print("   Seeding outreach: ran <7 days ago — nothing to do")
        return
    items, due = build(_int_arg("--count", DEFAULT_COUNT))
    text = render(items, due)
    print(text)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    if not items and not due:
        return
    try:
        import mailer
        sent = mailer.send_email(f"✉️ Velluto Seeding-Outreach — {dt.date.today().isoformat()}", text)
    except Exception as e:
        print(f"   ⚠️  email failed: {e}")
        sent = False
    # Only a delivered digest counts as "handled". If the mail failed (no SMTP
    # credentials, network), the targets stay open and the next daily run retries;
    # the text is also in output/seeding_outreach.txt.
    if sent:
        _save_state(items)


if __name__ == "__main__":
    main()
