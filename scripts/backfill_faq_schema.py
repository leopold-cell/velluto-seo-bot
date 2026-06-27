#!/usr/bin/env python3
"""
Backfill FAQPage JSON-LD on already-published articles that show a visible FAQ
section but carry no FAQPage schema.

Background (GEO audit): structured FAQ answers are extracted preferentially by
LLM/AI-Overview answer engines. New articles already get FAQPage schema injected
at publish time (seo_bot._parse_primary); this one-off backfills the back-catalogue.

Safety: schema is built ONLY from the article's visible <details>/<summary> FAQ
(question = <summary>, answer = the rest of the <details>), so the structured data
always matches on-page content — no fabricated or mismatched markup. EN bodies only.
Idempotent. Dry-run by default; pass --apply to write.

Usage:
  python3 scripts/backfill_faq_schema.py            # dry-run
  python3 scripts/backfill_faq_schema.py --apply     # write
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from seo_bot import SHOPIFY_STORE, SHOPIFY_HEADERS, BLOG_ID

APPLY = "--apply" in sys.argv

_HAS_FAQPAGE = re.compile(r'"@type"\s*:\s*"FAQPage"', re.I)


def _list_articles() -> list[dict]:
    out, url = [], (
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        "?fields=id,title,handle,body_html&limit=250"
    )
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=20)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        nxt = None
        for part in r.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                nxt = part.split(";")[0].strip(" <>")
        url = nxt
    return out


def _extract_faq_pairs(body: str) -> list[tuple[str, str]]:
    """Pull (question, answer) pairs from the visible FAQ <details> blocks.
    Stored article body_html contains FAQ <details> only (TOC accordion is
    rendered by the theme, not stored in the body)."""
    pairs: list[tuple[str, str]] = []
    for m in re.finditer(r'<details\b[^>]*>(.*?)</details>', body or "", re.DOTALL | re.I):
        inner = m.group(1)
        qm = re.search(r'<summary[^>]*>(.*?)</summary>', inner, re.DOTALL | re.I)
        if not qm:
            continue
        q = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', qm.group(1))).strip()
        a = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', inner[qm.end():])).strip()
        if q and a:
            pairs.append((q, a))
    return pairs


def _build_faq_schema(pairs: list[tuple[str, str]]) -> str:
    main_entity = [{
        "@type": "Question",
        "name": q,
        "acceptedAnswer": {"@type": "Answer", "text": a[:500]},
    } for q, a in pairs]
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": main_entity,
    }, ensure_ascii=False, indent=2)


def _update_en_body(aid: int, body: str) -> bool:
    r = requests.put(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{aid}.json",
        headers=SHOPIFY_HEADERS,
        json={"article": {"id": aid, "body_html": body}},
        timeout=20,
    )
    return r.status_code == 200


def main():
    print(f"=== backfill_faq_schema.py [{'APPLY' if APPLY else 'DRY-RUN'}] ===\n")
    articles = _list_articles()
    print(f"{len(articles)} articles in blog {BLOG_ID}\n")

    backfilled = skipped_has = skipped_nofaq = 0
    for a in articles:
        aid, title, body = a["id"], a.get("title", ""), a.get("body_html", "")
        if _HAS_FAQPAGE.search(body or ""):
            skipped_has += 1
            continue
        pairs = _extract_faq_pairs(body)
        if not pairs:
            skipped_nofaq += 1
            continue

        schema = _build_faq_schema(pairs)
        new_body = f'{body}\n<script type="application/ld+json">\n{schema}\n</script>\n'
        print(f"[FAQ] '{title[:50]}' (#{aid}) — {len(pairs)} Q&A → FAQPage schema")
        if APPLY:
            print(f"     {'✅ updated' if _update_en_body(aid, new_body) else '❌ failed'}")
        backfilled += 1

    print("\n=== Summary ===")
    print(f"Backfilled (visible FAQ, no schema): {backfilled}")
    print(f"Already had FAQPage schema:          {skipped_has}")
    print(f"No visible FAQ section:              {skipped_nofaq}")
    if not APPLY:
        print("\nDRY-RUN — no changes written. Re-run with --apply to backfill.")


if __name__ == "__main__":
    main()
