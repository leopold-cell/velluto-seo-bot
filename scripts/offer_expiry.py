#!/usr/bin/env python3
"""
Remove expired time-limited offers from published articles.

WHY
An evergreen article outlives a limited offer. The Chromo 2-for-1 ends 30 Nov 2026
(config/active_offers.yml); an article written in October would keep advertising it
into December, which is misleading advertising (§ 5 UWG) and a retro-fit nobody
wants. The queue briefs the model to wrap the offer in
    <p class="velluto-offer" data-offer-id="…" data-offer-ends="YYYY-MM-DD">…</p>
so expiry is mechanical, not a judgement call.

WHAT IT DOES
  1. Reads every published article.
  2. Removes each element that CARRIES the marker and whose data-offer-ends is
     before today (so the offer ends after the inclusive end date, i.e. 1 Dec).
     Only the bot's own marked element is touched, nothing else in the body.
  3. REPORTS — never edits — articles that still mention an expired offer's wording
     without the marker (the model did not follow the markup). Those need a human.

Idempotent and cheap: once nothing is expired, a daily run reads the article list
and exits. Dry-run by default; run.sh passes --apply.

Usage:
  python3 scripts/offer_expiry.py            # dry-run
  python3 scripts/offer_expiry.py --apply
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFERS = os.path.join(ROOT, "config", "active_offers.yml")
OUT = os.path.join(ROOT, "data", "offer_expiry.json")
APPLY = "--apply" in sys.argv

# <p ...data-offer-ends="2026-11-30"...>...</p>  (any tag, non-nested)
_MARKED = re.compile(
    r"<(?P<tag>p|div|span)\b[^>]*\bdata-offer-ends=[\"'](?P<end>\d{4}-\d{2}-\d{2})[\"'][^>]*>"
    r".*?</(?P=tag)>\s*", re.S | re.I)


def strip_expired(body: str, today: dt.date) -> tuple[str, int]:
    """Return (new_body, removed). A marker without a parseable date is left alone:
    deleting on a guess is worse than leaving a sentence for a human."""
    removed = 0

    def _sub(m: re.Match) -> str:
        nonlocal removed
        try:
            end = dt.date.fromisoformat(m.group("end"))
        except ValueError:
            return m.group(0)
        if today > end:
            removed += 1
            return ""
        return m.group(0)

    return _MARKED.sub(_sub, body), removed


def unmarked_mentions(body: str, offers: list[dict], today: dt.date) -> list[str]:
    """Expired offers whose headline wording is still in the body outside a marker."""
    cleaned = _MARKED.sub("", body)
    low = re.sub(r"<[^>]+>", " ", cleaned).lower()
    hits = []
    for o in offers:
        if today > o["ends"] and o.get("headline", "").lower() in low:
            hits.append(o["id"])
    return hits


def main() -> None:
    import requests
    import yaml
    from seo_bot import BLOG_ID, SHOPIFY_HEADERS, SHOPIFY_STORE

    offers = (yaml.safe_load(open(OFFERS, encoding="utf-8")) or {}).get("offers") or []
    today = dt.date.today()
    expired = [o for o in offers if today > o["ends"]]
    if not expired:
        nxt = min((o["ends"] for o in offers), default=None)
        print(f"   Offer-Expiry: nichts abgelaufen"
              + (f" (nächstes Ende {nxt})" if nxt else ""))
        return

    api = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
    url = (f"{api}/blogs/{BLOG_ID}/articles.json"
           "?fields=id,handle,body_html&limit=250&published_status=published")
    arts = []
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        arts.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)

    print(f"=== offer_expiry [{'APPLY' if APPLY else 'DRY-RUN'}] — "
          f"{len(expired)} abgelaufene(s) Angebot(e), {len(arts)} Artikel ===\n")
    cleaned, manual = [], []
    for a in arts:
        body = a.get("body_html") or ""
        new_body, n = strip_expired(body, today)
        if n:
            print(f"  ✂ {a['handle']}: {n} abgelaufene(r) Angebotsabsatz")
            if APPLY:
                resp = requests.put(f"{api}/blogs/{BLOG_ID}/articles/{a['id']}.json",
                                    headers=SHOPIFY_HEADERS, timeout=30,
                                    json={"article": {"id": a["id"], "body_html": new_body}})
                if resp.status_code in (200, 201):
                    cleaned.append(a["handle"])
                else:
                    print(f"     ✗ Schreiben fehlgeschlagen: HTTP {resp.status_code}")
        left = unmarked_mentions(new_body, expired, today)
        if left:
            manual.append({"handle": a["handle"], "offers": left})
            print(f"  ⚠️  {a['handle']}: erwähnt {left} OHNE Markierung — von Hand prüfen")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"date": today.isoformat(), "cleaned": cleaned, "needs_human": manual},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{len(cleaned)} bereinigt, {len(manual)} brauchen einen Blick."
          if APPLY else "\nDRY-RUN — mit --apply entfernen.")


if __name__ == "__main__":
    main()
