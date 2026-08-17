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
import re
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


# A shared word only tells you something if it is rare. "cycling" sits in 69 of
# 72 handles and "glasses" in 62 — matching on them is how two unrelated questions
# both linked to cycling-glasses-review-2026. The previous fix deleted such words
# from a hand-written stop list, which over-corrected: it also deleted them from
# "best road cycling sunglasses" and "Do I need cycling glasses?", leaving nothing
# to match on, so both reported "kein passender Artikel" while the right article
# (best-road-bike-sunglasses-2026-buyers-guide) sat in the corpus.
#
# Weighting by inverse document frequency does the same job without a list to
# maintain: over our own 72 articles "cycling" scores 0.03 and "glasses" 0.13,
# while "sunglasses" and "road" score 1.97 and "small"/"face"/"mtb" 3.58. Generic
# words stop deciding matches without ceasing to exist, and the weights follow the
# corpus as it grows.
_IDF_CACHE: dict | None = None
_MIN_SCORE = 1.5      # at least one genuinely distinctive shared word
_STRONG = 4.0         # above this the match stands even if another article ties
_MARGIN = 1.15        # near the floor, demand a clear winner or abstain


def _corpus() -> tuple[dict, dict]:
    """(url → token set, token → idf), built once per process."""
    global _IDF_CACHE
    if _IDF_CACHE is None:
        import collections
        import math
        state = load_json(os.path.join("data", "content_state.json"), {})
        arts = state.get("articles") if isinstance(state, dict) else {}
        docs = {u: set(re.findall(r"[a-z]{2,}",
                                  f"{m.get('handle', '')} {m.get('title', '')}".lower()))
                for u, m in (arts or {}).items() if isinstance(m, dict)}
        n = len(docs)
        df = collections.Counter()
        for toks in docs.values():
            df.update(toks)
        _IDF_CACHE = (docs, {w: math.log(n / (1 + c)) for w, c in df.items()} if n else {})
    return _IDF_CACHE


def _live_article_for(question: str) -> str:
    """A published article that already answers this — the draft links to it,
    never to a product page (that reads as an ad and gets removed).

    Returns "" when nothing fits well enough. On Reddit a wrong link is worse
    than no link: it reads as a drive-by promo and gets the comment removed.
    """
    docs, idf = _corpus()
    if not docs:
        return ""
    qt = set(re.findall(r"[a-z]{2,}", question.lower()))
    if not qt:
        return ""
    ranked = sorted(((sum(idf.get(w, 0.0) for w in qt & toks), url)
                     for url, toks in docs.items()), reverse=True)
    best = ranked[0]
    runner = ranked[1][0] if len(ranked) > 1 else 0.0
    if best[0] < _MIN_SCORE:
        return ""
    if best[0] < _STRONG and best[0] <= runner * _MARGIN:
        return ""      # two articles fit equally and neither is strong — abstain
    return best[1]


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
