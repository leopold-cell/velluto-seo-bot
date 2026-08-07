#!/usr/bin/env python3
"""
Daily Reddit worklist — real open threads + a ready draft. You post, not a bot.

WHAT THIS IS NOT
It does not touch Reddit. No login, no automation, no posting. Reddit's User
Agreement prohibits automated access outside the official API, and enforcement is
behavioural (timing, headless markers, IP) rather than content-based — a script
driving a browser gets flagged however good the text is, and the penalty can
reach the DOMAIN, not just the account. Since data/seeding_targets.json ranks
reddit.com as target #1 ("AI cites it but not us"), burning it would destroy the
exact asset this is meant to build.

Threads are found through the same public web search the repo already uses for
competitor research (ddgs, see seo_optimizer.py) — reading public search results,
not scraping Reddit.

WHAT IT GIVES YOU, every morning:
  · the open threads matching the questions where AI cites Reddit instead of us
  · a draft answer, already through check_compliance
  · the Velluto article that backs it up
  · the subreddit's standing rule, so the read-check takes seconds

You decide per thread whether the answer genuinely fits — that judgement is the
part that earns upvotes, and upvoted threads are the ones AI engines cite. A
scheduled post ignores whether the thread deserves a reply, which is why
automating this produces bans instead of citations.

DISCLOSURE IS NOT OPTIONAL. Every draft carries an affiliation line. Undisclosed
brand posts are Schleichwerbung (§ 5a Abs. 4 UWG, Anhang Nr. 11 zu § 3 Abs. 3),
and most cycling subs remove them on sight. Disclosed manufacturer answers are
both legal and, in practice, welcome.

Usage:
  python3 scripts/reddit_daily.py              # today's list
  python3 scripts/reddit_daily.py --count 5
  python3 scripts/reddit_daily.py --markdown   # for the digest mail
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_COUNT = 3
DISCLOSURE = "Disclosure: I build Velluto, so take this with the appropriate pinch of salt."

# Standing rules per subreddit — shown with every thread so the read-check is quick.
SUB_RULES = {
    "cycling":       "No self-promotion. Only answer if the reply works without the link.",
    "bicycling":     "As r/cycling — promotional posts get removed.",
    "RoadCycling":   "Smaller, tolerant of detail. Experience before link.",
    "gravelcycling": "Genuine gravel topics only.",
    "wielrennen":    "Write Dutch. Small community, promotion is obvious.",
    "Velo":          "Technical questions welcome, disclose affiliation.",
}


def _threads_for(question: str, limit: int = 3) -> list[dict]:
    """Open Reddit threads on this topic, via public web search."""
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    out = []
    try:
        with DDGS() as d:
            for hit in d.text(f"site:reddit.com {question}", max_results=limit * 3):
                url = hit.get("href") or hit.get("url") or ""
                m = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)/comments/", url)
                if not m:
                    continue
                out.append({"url": url.split("?")[0], "sub": m.group(1),
                            "title": (hit.get("title") or "").strip()[:110]})
                if len(out) >= limit:
                    break
    except Exception as e:
        print(f"   ⚠️  thread search failed: {e}")
    return out


def build(count: int = DEFAULT_COUNT) -> list[dict]:
    from geo_gaps import collect_gaps
    from reddit_drafts import _draft_text, _live_article_for
    try:
        from briefs.quality_gate import check_compliance
    except Exception:
        check_compliance = None

    # Only questions where AI cites Reddit and not us — that is the whole point.
    gaps = collect_gaps()
    candidates = []
    for market, rows in gaps.items():
        for r in rows:
            if any("reddit" in d for d in r.get("rivals", [])):
                candidates.append({**r, "market": market})
    candidates.sort(key=lambda r: -r["misses"])

    items = []
    for gap in candidates:
        if len(items) >= count:
            break
        q = gap["question"]
        threads = _threads_for(q, limit=2)
        if not threads:
            continue
        url = _live_article_for(q)
        title, body = _draft_text(q, url)
        body = f"{body}\n\n{DISCLOSURE}"
        issues = check_compliance({"title": title, "body_html": body}) if check_compliance else []
        items.append({"question": q, "market": gap["market"], "misses": gap["misses"],
                      "threads": threads, "draft_title": title, "draft_body": body,
                      "source": url, "legal_issues": issues})
    return items


def render(items: list[dict], markdown: bool = False) -> str:
    if not items:
        return ("Reddit-Tagesliste: keine passenden offenen Threads gefunden. "
                "Entweder fehlen Messläufe (geo_gaps braucht 2+) oder die Suche lieferte nichts.")
    L = [f"Reddit-Tagesliste ({len(items)}) — du postest, nichts läuft automatisch", ""]
    for i, it in enumerate(items, 1):
        L.append(f"── #{i}  [{it['market'].upper()}]  KI zitiert hier Reddit, uns nicht "
                 f"({it['misses']}× verfehlt)")
        L.append(f"   Frage: {it['question']}")
        L.append("   Offene Threads:")
        for t in it["threads"]:
            rule = SUB_RULES.get(t["sub"], "Subreddit-Regeln vor dem Posten prüfen.")
            L.append(f"     • r/{t['sub']} — {t['title']}")
            L.append(f"       {t['url']}")
            L.append(f"       Regel: {rule}")
        if it["legal_issues"]:
            L.append("   ⛔ NICHT POSTEN — Legal-Gate:")
            for x in it["legal_issues"]:
                L.append(f"      {x[:110]}")
        L.append("   Entwurf:")
        for line in (it["draft_body"] or "").splitlines():
            L.append(f"      {line}")
        L.append(f"   Quelle: {it['source'] or '— kein passender Artikel'}")
        L.append("")
    L.append("Vorgehen: Thread lesen → passt die Antwort wirklich? → Entwurf anpassen → "
             "posten. Lieber keinen Beitrag als einen unpassenden.")
    return "\n".join(L)


OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "output", "reddit_daily.txt")


def main() -> None:
    count = DEFAULT_COUNT
    if "--count" in sys.argv:
        i = sys.argv.index("--count")
        if i + 1 < len(sys.argv):
            count = max(1, int(sys.argv[i + 1]))
    text = render(build(count), markdown="--markdown" in sys.argv)
    print(text)
    # Written to disk so the daily mail can include it without re-running the
    # search — daily_report must not depend on network calls.
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        print(f"   ⚠️  could not write {OUT}: {e}")


if __name__ == "__main__":
    main()
