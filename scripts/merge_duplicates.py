#!/usr/bin/env python3
"""
Merge articles that compete for the same query — keyword cannibalisation.

WHY
The blog holds several sets of articles aimed at one query: three pages target
"best road cycling glasses 2026", two "best cycling sunglasses 2026", four sit
on Oakley-alternative variants. Google splits links, clicks and relevance
signals across the set, so none of them ranks as the one page could — and at
average position 6.5 the site's problem IS position, not click-through (the CTR
audit of 2026-08-21 found six of seven top pages already at or above the
realistic rate for where they rank).

WHAT IT DOES
  1. Groups published articles whose handles reduce to the SAME core keyword
     after stripping year/format/claim words. Equality, not similarity — a
     wrong merge deletes a page, so near-misses (high overlap, not equal) are
     only reported for a human to judge.
  2. Within each group, asks GSC (90 days, exact per-page) which variant earns
     the clicks. The winner is the one readers already chose. No GSC access →
     report only, never guess.
  3. --apply: unpublishes each loser, then 301s its path to the winner.
     Unpublish FIRST — Shopify redirects only fire once the path 404s, so the
     other order leaves a dead page live. Locale prefixes (/de/, /nl/ …) are
     handled by Shopify's redirect layer.

A merge is an editorial decision with a destructive half, so --apply runs only when a
human reads the plan. --auto (run.sh, 7-day gate) exists for stretches when nobody can
reach the server: it applies only groups where the winner is unambiguous (see
_auto_ok), at most MAX_AUTO_LOSERS per run, and logs to data/merge_duplicates_log.json.
Losers are unpublished, never deleted, so every merge can be undone.

Usage:
  python3 scripts/merge_duplicates.py            # plan only
  python3 scripts/merge_duplicates.py --apply
  python3 scripts/merge_duplicates.py --auto     # guarded, weekly
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from seo_bot import BLOG_ID, SHOPIFY_HEADERS, SHOPIFY_STORE

API = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
SITE = "https://velluto-shop.com"
BLOG_PATH = "/blogs/velluto-the-magazine"
AUTO = "--auto" in sys.argv
APPLY = "--apply" in sys.argv or AUTO
LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "merge_duplicates_log.json")
MAX_AUTO_LOSERS = 5          # per run
CLICKS_AMBIGUOUS = 10        # two members at or above this: a human decides
MIN_AGE_DAYS = 14            # a zero-click winner needs an old member to be credible
# Pages that must never be a merge loser (or part of an automatic merge at all).
_PROTECTED = re.compile(r"gift|geschenk|night-glow|chromo|black-friday", re.I)

# Words that describe the FORMAT or the CLAIM of an article, not its topic.
# Two handles that agree after removing these target the same query.
_STRIP = {
    "2025", "2026", "2027", "best", "the", "a", "an", "and", "for", "in", "of",
    "guide", "complete", "buyers", "buying", "criteria", "top", "picks",
    "tested", "ranked", "compared", "review", "honest", "answer", "explained",
    "what", "actually", "makes", "them", "good", "full", "comparison",
    "how", "much", "to", "spend", "worth", "it", "why", "riders", "switch",
    # Format/claim words that hid two real duplicate pairs: roka-vs-velluto-
    # …-specs-2026 and …-same-performance-better-value-2026 are one comparison,
    # and "velluto" as slug decoration split best-oakley-alternative-cycling-
    # sunglasses-2026-velluto from oakley-alternative-cycling-sunglasses-….
    # Stripping "vs" is safe: comparisons stay distinct through the competitor
    # NAMES, which are never stripped.
    "vs", "specs", "same", "better", "value", "performance", "velluto",
    # "real" hid the third "are expensive glasses worth it" variant: the 2026-08-21
    # run merged two of them while …-worth-it-the-real-answer sat in the near-miss
    # list. With "real" stripped it reduces to the same core and the next run
    # folds it into the winner.
    "real",
}


def core(handle: str) -> frozenset:
    toks = [t for t in re.split(r"-+", handle.lower()) if t]
    return frozenset(t for t in toks if t not in _STRIP and not t.isdigit())


def fetch_articles() -> list[dict]:
    out, url = [], (f"{API}/blogs/{BLOG_ID}/articles.json"
                    "?fields=id,handle,title,published_at&limit=250&published_status=published")
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
    return out


def gsc_stats(handles: list[str]) -> dict[str, dict]:
    """{handle: {clicks, impressions}} over 90 days, exact page match."""
    try:
        from ctr_optimizer import _gsc_query, _gsc_token
    except ImportError:
        return {}
    token = _gsc_token()
    if not token:
        return {}
    import datetime
    today = datetime.date.today()
    out = {}
    for h in handles:
        try:
            rows = _gsc_query(token, {
                "startDate": (today - datetime.timedelta(days=90)).isoformat(),
                "endDate": today.isoformat(),
                "dimensionFilterGroups": [{"filters": [
                    {"dimension": "page", "operator": "equals",
                     "expression": f"{SITE}{BLOG_PATH}/{h}"}]}],
                "rowLimit": 1,
            })
            out[h] = {"clicks": int(rows[0]["clicks"]) if rows else 0,
                      "impressions": int(rows[0]["impressions"]) if rows else 0}
        except Exception as e:
            print(f"   ⚠️  GSC für {h}: {str(e)[:60]}")
    return out


def unpublish(article_id: int) -> bool:
    r = requests.put(f"{API}/blogs/{BLOG_ID}/articles/{article_id}.json",
                     headers=SHOPIFY_HEADERS, timeout=30,
                     json={"article": {"id": article_id, "published": False}})
    return r.status_code in (200, 201)


def redirect(old_handle: str, new_handle: str) -> bool:
    r = requests.post(f"{API}/redirects.json", headers=SHOPIFY_HEADERS, timeout=30,
                      json={"redirect": {"path": f"{BLOG_PATH}/{old_handle}",
                                         "target": f"{BLOG_PATH}/{new_handle}"}})
    if r.status_code == 422 and "already" in r.text.lower():
        return True                      # rerun after a partial apply
    return r.status_code in (200, 201)


def _age_days(a: dict) -> int:
    import datetime
    try:
        d = datetime.datetime.fromisoformat((a.get("published_at") or "").replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - d).days
    except Exception:
        return 0


def _auto_ok(ranked: list[dict], stats: dict) -> str:
    """'' when the group may be merged unattended, else the reason it may not."""
    if any(_PROTECTED.search(a["handle"]) for a in ranked):
        return "geschützter Artikel in der Gruppe"
    if not all(a["handle"] in stats for a in ranked):
        return "GSC-Daten unvollständig"
    clicks = [stats[a["handle"]]["clicks"] for a in ranked]
    # A runner-up that earns real clicks AND is close to the winner means there is no
    # clear reader favourite; 40 vs 12 clicks is a clear one.
    if len(clicks) > 1 and clicks[1] >= CLICKS_AMBIGUOUS and clicks[1] * 2 > clicks[0]:
        return f"mehrdeutig, Zweiter hat {clicks[1]} von {clicks[0]} Klicks"
    if clicks[0] == 0 and max(_age_days(a) for a in ranked) < MIN_AGE_DAYS:
        return "zu früh, noch keine Klickdaten"
    return ""


def _load_log() -> list:
    try:
        import json
        return json.load(open(LOG, encoding="utf-8"))
    except Exception:
        return []


def _save_log(log: list) -> None:
    import json
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    json.dump(log[-60:], open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main() -> None:
    arts = fetch_articles()
    run_log = _load_log() if AUTO else []
    if AUTO:
        import datetime
        from geo_questions import gate_ok
        if not gate_ok(run_log, force="--force" in sys.argv, days=7):
            print("   Merge: nächster automatischer Lauf frühestens 7 Tage nach dem letzten.")
            return
    print(f"=== merge_duplicates [{'AUTO' if AUTO else 'APPLY' if APPLY else 'PLAN'}] — "
          f"{len(arts)} veröffentlichte Artikel ===\n")

    # Two ways two handles are the same page. (1) EQUAL core after stripping
    # year/format/claim words. (2) One handle IS another plus a suffix — e.g.
    # best-oakley-alternatives-for-cyclists-2026 and its -lighter-cheaper /
    # -lighter-smarter variants. The suffix rule is deliberately narrow (B must
    # start with A + "-", A a real published handle), so it catches spun variants
    # of one page without merging genuinely-distinct sub-intent: the three
    # anti-fog pages (…-for-cold-climbs / -for-summer / -for-wet-weather) share no
    # such prefix and are left alone. Union-find joins both relations into groups.
    handled = [a for a in arts if a.get("handle")]
    parent: dict[str, str] = {a["handle"]: a["handle"] for a in handled}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        parent[find(x)] = find(y)

    groups: dict[frozenset, list[dict]] = {}       # by core, for the near-miss report
    by_core: dict[frozenset, str] = {}
    for a in handled:
        c = core(a["handle"])
        if not c:
            continue
        groups.setdefault(c, []).append(a)
        if c in by_core:
            union(a["handle"], by_core[c])
        else:
            by_core[c] = a["handle"]

    handles_sorted = sorted((a["handle"] for a in handled), key=len)
    for i, short in enumerate(handles_sorted):
        for longer in handles_sorted[i + 1:]:
            if longer.startswith(short + "-"):
                union(short, longer)

    by_handle_obj = {a["handle"]: a for a in handled}
    comp: dict[str, list[dict]] = {}
    for h in parent:
        comp.setdefault(find(h), []).append(by_handle_obj[h])
    # Key each group by the shared core of its longest-covered member, for display.
    dupes = {}
    for root, members in comp.items():
        if len(members) > 1:
            key = core(min((m["handle"] for m in members), key=len)) or frozenset({root})
            dupes[key] = members

    # Near-misses: big overlap but not equal. Reported, never acted on.
    keys = [k for k in groups if k]
    near = []
    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1:]:
            inter = len(k1 & k2)
            if k1 != k2 and inter and inter / len(k1 | k2) >= 0.75:
                near.append((groups[k1][0]["handle"], groups[k2][0]["handle"]))

    if not dupes:
        print("✅ Keine exakten Keyword-Dubletten.")
    stats_all = gsc_stats([a["handle"] for v in dupes.values() for a in v])
    if dupes and not stats_all:
        print("⚠️  Keine GSC-Daten (Credentials fehlen?) — nur Plan, keine "
              "Sieger-Entscheidung. Auf dem VPS ausführen.\n")

    merged = 0
    done: list[dict] = []
    held: list[dict] = []
    for k, members in sorted(dupes.items(), key=lambda kv: -len(kv[1])):
        print(f"── Ziel-Keyword: {' '.join(sorted(k))}")
        ranked = sorted(members, key=lambda a: (
            -(stats_all.get(a["handle"], {}).get("clicks", 0)),
            -(stats_all.get(a["handle"], {}).get("impressions", 0)),
            -_age_days(a)))
        for i, a in enumerate(ranked):
            s = stats_all.get(a["handle"], {})
            tag = "SIEGER " if i == 0 else "→ 301  "
            print(f"   {tag} {a['handle'][:64]}  "
                  f"({s.get('clicks', '?')} Kl / {s.get('impressions', '?')} Impr, 90d)")
        if not APPLY or not stats_all:
            print()
            continue
        winner = ranked[0]
        if AUTO:
            why = _auto_ok(ranked, stats_all)
            if not why and merged + len(ranked) - 1 > MAX_AUTO_LOSERS:
                why = f"Limit von {MAX_AUTO_LOSERS} Zusammenlegungen pro Lauf erreicht"
            if why:
                print(f"   ⏸ nicht automatisch: {why}\n")
                held.append({"winner": winner["handle"], "reason": why})
                continue
        for loser in ranked[1:]:
            ok1 = unpublish(loser["id"])
            ok2 = redirect(loser["handle"], winner["handle"]) if ok1 else False
            print(f"   {'✓' if ok1 and ok2 else '✗'} {loser['handle']} → "
                  f"{winner['handle']}"
                  + ("" if ok1 and ok2 else "  (unpublish/redirect fehlgeschlagen)"))
            merged += ok1 and ok2
            if ok1 and ok2:
                done.append({"loser": loser["handle"], "winner": winner["handle"],
                             "winner_clicks": stats_all.get(winner["handle"], {}).get("clicks"),
                             "loser_clicks": stats_all.get(loser["handle"], {}).get("clicks")})
        print()

    if near:
        print("── Ähnlich, aber NICHT automatisch zusammengelegt (von Hand prüfen):")
        for a, b in near[:10]:
            print(f"   ? {a}\n     {b}")
    if AUTO and stats_all:
        import datetime
        run_log.append({"date": datetime.date.today().isoformat(),
                        "merged": done, "held": held,
                        "near_misses": [list(n) for n in near[:10]]})
        _save_log(run_log)
    if APPLY:
        print(f"\n{merged} Artikel zusammengelegt. Die Sieger-URLs in der GSC "
              "neu indexieren lassen; content_retrofit --force aktualisiert den Bestand.")
    else:
        print("\nPLAN — nichts geändert. Anwenden mit --apply auf dem VPS.")


if __name__ == "__main__":
    main()
