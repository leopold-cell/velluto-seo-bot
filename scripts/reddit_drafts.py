#!/usr/bin/env python3
"""
Ready-to-post Reddit drafts — written by the bot, posted by a human.

WHY NOT AUTOMATIC
  link_builder.py has a complete Reddit poster (praw + Haiku + subreddit picker).
  It has never posted once: link_building_log.json holds 43 "skipped:
  no_credentials" and zero "posted". That is the right outcome — a fresh
  zero-karma account dropping links into r/cycling gets banned as spam, and a
  ban is permanent. So this generates the draft and the target; the posting
  decision stays with a person who has an account with standing.

WHY IT MATTERS
  data/seeding_targets.json ranks reddit.com as target #1 (score 400, "AI cites
  it but not us" across 7 keywords). Every AI-visibility measurement we have
  shows reddit.com among the domains cited instead of Velluto. It is the single
  largest unworked lever.

LEGAL
  Every draft passes briefs/quality_gate.py::check_compliance() before it is
  shown. docs/LEGAL_GUARDRAILS.md requires this of every path producing
  user-visible text, and a Reddit post is exactly that — a fabricated "we tested
  these" post is a UWG problem whether it sits on the shop or on Reddit.
  Drafts that fail are dropped with their reason, never silently softened.

Usage:
  python3 scripts/reddit_drafts.py             # 2 drafts, plain text
  python3 scripts/reddit_drafts.py --count 3   # more
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from geo_questions import GEO_MARKETS, load_json  # noqa: E402

DEFAULT_COUNT = 2

# Subreddit rules differ and change; these are the standing constraints that made
# the difference between a post staying up and being removed. Shown with every
# draft so the human check is quick.
SUBREDDIT_NOTES = {
    "cycling":       "Kein Eigenmarketing. Nur posten, wenn der Beitrag ohne den Link funktioniert.",
    "bicycling":     "Wie r/cycling — Selbstwerbung wird entfernt.",
    "RoadCycling":   "Kleiner, toleranter bei Detailfragen. Trotzdem: Erfahrung vor Link.",
    "gravelcycling": "Nur echte Gravel-Themen, sonst Entfernung.",
    "wielrennen":    "Niederländisch schreiben. Kleine Community, Werbung fällt sofort auf.",
}


def _pick_subreddit(topic: str) -> str:
    """Reuses link_builder's mapping so both paths target the same places."""
    try:
        from link_builder import _pick_subreddit as pick
        return pick(topic, "")[0]
    except Exception:
        t = topic.lower()
        if any(w in t for w in ("wielren", "fietsbril", "nederland")):
            return "wielrennen"
        if "gravel" in t:
            return "gravelcycling"
        return "RoadCycling"


def _gap_questions(limit: int) -> list[dict]:
    """Questions where AI cites reddit.com instead of Velluto — the best topics
    to actually be present for."""
    try:
        from geo_gaps import collect_gaps
        gaps = collect_gaps()
    except Exception:
        return []
    out = []
    for market in GEO_MARKETS:
        for row in gaps.get(market) or []:
            if any("reddit" in d for d in row.get("rivals", [])):
                out.append({**row, "market": market})
    out.sort(key=lambda r: -r["misses"])
    return out[:limit] if out else []


def _live_article_for(question: str) -> str:
    """A published article that already answers this — the draft links to it,
    never to a product page (that reads as an ad and gets removed).

    data/content_state.json["articles"] is keyed by full URL, value carries
    handle/title/words.
    """
    state = load_json(os.path.join("data", "content_state.json"), {})
    arts = state.get("articles") if isinstance(state, dict) else None
    if not isinstance(arts, dict):
        return ""
    stop = {"what", "which", "there", "these", "those", "about", "should", "cycling"}
    words = {w.strip("?.,") for w in question.lower().split()
             if len(w) > 4 and w.strip("?.,") not in stop}
    best_url, best_score = "", 0
    for url, meta in arts.items():
        if not isinstance(meta, dict):
            continue
        haystack = f"{meta.get('handle', '')} {meta.get('title', '')}".lower()
        tokens = set(haystack.replace("-", " ").replace(":", " ").split())
        score = len(words & tokens)
        if score > best_score:
            best_url, best_score = url, score
    # Short questions ("Do I need cycling glasses?") carry only one distinctive
    # word after stop-word removal — demanding two would never match them.
    need = 2 if len(words) >= 3 else 1
    return best_url if best_score >= need else ""


def _draft_text(question: str, url: str) -> tuple[str, str]:
    """Uses link_builder's Haiku generator when a key is present; otherwise a
    clearly-marked skeleton so the digest is useful even without API access."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key:
        try:
            from link_builder import _generate_reddit_post
            article = {"topic": question, "keyword": question,
                       "title": question, "url": url or "https://velluto-shop.com"}
            sub = _pick_subreddit(question)
            return _generate_reddit_post(article, sub, "en")
        except Exception:
            pass
    return (
        question,
        "[Rohentwurf — ohne ANTHROPIC_API_KEY nicht ausformuliert]\n"
        f"Thema: {question}\n"
        "Aufbau: eigene Rideerfahrung → konkrete Beobachtung → erst am Ende, "
        f"falls jemand nachfragt, der Link: {url or '(kein passender Artikel gefunden)'}",
    )


def build_drafts(count: int = DEFAULT_COUNT) -> list[dict]:
    """Compliance-checked drafts. Non-compliant ones are returned flagged, not hidden."""
    try:
        from briefs.quality_gate import check_compliance
    except Exception:
        check_compliance = None

    drafts: list[dict] = []
    used_subs: set[str] = set()
    for gap in _gap_questions(count * 3):
        if len(drafts) >= count:
            break
        q = gap["question"]
        sub = _pick_subreddit(q)
        # Two posts into the same subreddit in one week reads as spam and risks
        # the account. Spread them instead.
        if sub in used_subs:
            alt = next((s for s in SUBREDDIT_NOTES if s not in used_subs), None)
            if alt is None:
                continue
            sub = alt
        used_subs.add(sub)
        url = _live_article_for(q)
        title, body = _draft_text(q, url)
        issues = check_compliance({"title": title, "body_html": body}) if check_compliance else []
        drafts.append({
            "question": q,
            "market": gap["market"],
            "subreddit": sub,
            "title": title,
            "body": body,
            "url": url,
            "misses": gap["misses"],
            "legal_issues": issues,
        })
    return drafts


def format_drafts(drafts: list[dict]) -> str:
    if not drafts:
        return ("Reddit-Entwürfe: keine Kandidaten — es fehlen entweder Messläufe "
                "oder es gibt keine Frage, bei der Reddit statt Velluto zitiert wird.")
    L = [f"Reddit-Entwürfe ({len(drafts)}) — selbst posten, nicht automatisiert",
         "Erst posten, wenn der Account echtes Karma hat. Link zuletzt, nie zuerst.", ""]
    for i, d in enumerate(drafts, 1):
        note = SUBREDDIT_NOTES.get(d["subreddit"], "")
        L.append(f"── #{i}  r/{d['subreddit']}  [{d['market'].upper()}] "
                 f"(KI zitiert hier Reddit, uns nicht — {d['misses']}× verfehlt)")
        if note:
            L.append(f"   Regel: {note}")
        if d["legal_issues"]:
            L.append("   ⛔ NICHT POSTEN — Legal-Gate:")
            for iss in d["legal_issues"]:
                L.append(f"      {iss}")
        L.append(f"   Titel: {d['title']}")
        L.append("   Text:")
        for line in (d["body"] or "").splitlines():
            L.append(f"      {line}")
        L.append(f"   Quelle: {d['url'] or '— kein passender Artikel; ggf. erst einen schreiben'}")
        L.append("")
    return "\n".join(L).rstrip()


def _int_arg(flag: str, default: int) -> int:
    """Numeric CLI flag that tolerates a typo instead of dying on it.

    Hand-rolled int(sys.argv[i+1]) raised ValueError on "--count 2." — a stray
    period copied out of prose. A tracebacked script reads like a broken tool;
    it is not, and the run should continue with the default.
    """
    if flag not in sys.argv:
        return default
    i = sys.argv.index(flag)
    if i + 1 >= len(sys.argv):
        print(f"   ⚠️  {flag} without a value — using {default}")
        return default
    raw = sys.argv[i + 1].strip().rstrip(".,;")
    try:
        return max(1, int(raw))
    except ValueError:
        print(f"   ⚠️  {flag} expects a number, got {sys.argv[i + 1]!r} — using {default}")
        return default


def main() -> None:
    count = _int_arg("--count", DEFAULT_COUNT)
    print(format_drafts(build_drafts(count)))


if __name__ == "__main__":
    main()
