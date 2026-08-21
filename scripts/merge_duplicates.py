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

NOT a pipeline step on purpose. A merge is a one-time editorial decision with a
destructive half; it runs when a human reads the plan and says apply.

Usage:
  python3 scripts/merge_duplicates.py            # plan only
  python3 scripts/merge_duplicates.py --apply
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
APPLY = "--apply" in sys.argv

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
}


def core(handle: str) -> frozenset:
    toks = [t for t in re.split(r"-+", handle.lower()) if t]
    return frozenset(t for t in toks if t not in _STRIP and not t.isdigit())


def fetch_articles() -> list[dict]:
    out, url = [], (f"{API}/blogs/{BLOG_ID}/articles.json"
                    "?fields=id,handle,title&limit=250&published_status=published")
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


def main() -> None:
    arts = fetch_articles()
    print(f"=== merge_duplicates [{'APPLY' if APPLY else 'PLAN'}] — "
          f"{len(arts)} veröffentlichte Artikel ===\n")

    groups: dict[frozenset, list[dict]] = {}
    for a in arts:
        if a.get("handle"):
            groups.setdefault(core(a["handle"]), []).append(a)
    dupes = {k: v for k, v in groups.items() if len(v) > 1 and k}

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
    for k, members in sorted(dupes.items(), key=lambda kv: -len(kv[1])):
        print(f"── Ziel-Keyword: {' '.join(sorted(k))}")
        ranked = sorted(members, key=lambda a: (
            -(stats_all.get(a["handle"], {}).get("clicks", 0)),
            -(stats_all.get(a["handle"], {}).get("impressions", 0))))
        for i, a in enumerate(ranked):
            s = stats_all.get(a["handle"], {})
            tag = "SIEGER " if i == 0 else "→ 301  "
            print(f"   {tag} {a['handle'][:64]}  "
                  f"({s.get('clicks', '?')} Kl / {s.get('impressions', '?')} Impr, 90d)")
        if not APPLY or not stats_all:
            print()
            continue
        winner = ranked[0]
        for loser in ranked[1:]:
            ok1 = unpublish(loser["id"])
            ok2 = redirect(loser["handle"], winner["handle"]) if ok1 else False
            print(f"   {'✓' if ok1 and ok2 else '✗'} {loser['handle']} → "
                  f"{winner['handle']}"
                  + ("" if ok1 and ok2 else "  (unpublish/redirect fehlgeschlagen)"))
            merged += ok1 and ok2
        print()

    if near:
        print("── Ähnlich, aber NICHT automatisch zusammengelegt (von Hand prüfen):")
        for a, b in near[:10]:
            print(f"   ? {a}\n     {b}")
    if APPLY:
        print(f"\n{merged} Artikel zusammengelegt. Die Sieger-URLs in der GSC "
              "neu indexieren lassen; content_retrofit --force aktualisiert den Bestand.")
    else:
        print("\nPLAN — nichts geändert. Anwenden mit --apply auf dem VPS.")


if __name__ == "__main__":
    main()
