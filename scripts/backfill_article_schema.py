#!/usr/bin/env python3
"""
Backfill Article JSON-LD on already-published articles that carry none.

Background: new articles get Article schema injected at publish time
(seo_bot.build_body_html). The back-catalogue predates that and has only
FAQPage (from scripts/backfill_faq_schema.py) — so for older articles the AI
engines get no author/publisher/date attribution at all, which is exactly the
provenance signal they use when deciding whether to cite a source.

Better dates than the live path: this reads each article's REAL published_at /
updated_at from Shopify instead of stamping "today". A back-dated article that
claims to be published today is a worse signal than no date.

Safety: EN bodies only, idempotent (skips anything that already has an Article
block), never touches the visible HTML — appends one <script> at the end.
Dry-run by default; pass --apply to write.

Usage:
  python3 scripts/backfill_article_schema.py            # dry-run
  python3 scripts/backfill_article_schema.py --apply    # write
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from seo_bot import SHOPIFY_STORE, SHOPIFY_HEADERS, BLOG_ID

APPLY = "--apply" in sys.argv

_HAS_ARTICLE = re.compile(r'"@type"\s*:\s*"Article"', re.I)
_IMG_SRC = re.compile(r'<img[^>]+src="([^"]+)"', re.I)
_META_DESC = re.compile(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', re.I)

LOGO = "https://velluto-shop.com/cdn/shop/files/velluto-logo.png"


def _list_articles() -> list[dict]:
    out, url = [], (
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        "?fields=id,title,handle,body_html,image,published_at,updated_at,summary_html"
        "&limit=250&published_status=published"
    )
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
    return out


def _cover(a: dict) -> str:
    img = a.get("image") or {}
    if isinstance(img, dict) and img.get("src"):
        return img["src"]
    m = _IMG_SRC.search(a.get("body_html") or "")
    return m.group(1) if m else ""


def _date(value: str) -> str:
    """Shopify ISO timestamp → YYYY-MM-DD ('' when absent)."""
    return (value or "")[:10]


def build_schema(a: dict) -> dict | None:
    headline = (a.get("title") or "").strip()[:110]
    if not headline:
        return None
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "image": _cover(a),
        "author":    {"@type": "Organization", "name": "Velluto"},
        "publisher": {
            "@type": "Organization", "name": "Velluto",
            "logo": {"@type": "ImageObject", "url": LOGO},
        },
    }
    pub, upd = _date(a.get("published_at", "")), _date(a.get("updated_at", ""))
    if pub:
        schema["datePublished"] = pub
    # Never claim it was modified before it was published.
    if upd and (not pub or upd >= pub):
        schema["dateModified"] = upd
    elif pub:
        schema["dateModified"] = pub

    summary = re.sub(r"<[^>]+>", " ", a.get("summary_html") or "").strip()
    if summary:
        schema["description"] = re.sub(r"\s+", " ", summary)[:300]
    return schema


def main() -> None:
    print(f"=== backfill_article_schema.py [{'APPLY' if APPLY else 'DRY-RUN'}] ===\n")
    articles = _list_articles()
    print(f"{len(articles)} published articles in blog {BLOG_ID}\n")

    todo, skipped = [], 0
    for a in articles:
        body = a.get("body_html") or ""
        if _HAS_ARTICLE.search(body):
            skipped += 1
            continue
        schema = build_schema(a)
        if schema:
            todo.append((a, schema))

    print(f"{skipped} already have Article schema · {len(todo)} to backfill\n")
    done = 0
    for a, schema in todo:
        print(f"• {a.get('handle', '')[:60]}  "
              f"(published {schema.get('datePublished', '?')})")
        if not APPLY:
            continue
        new_body = (a["body_html"]
                    + '\n<script type="application/ld+json">\n'
                    + json.dumps(schema, ensure_ascii=False, indent=2)
                    + '\n</script>\n')
        r = requests.put(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{a['id']}.json",
            headers=SHOPIFY_HEADERS, timeout=20,
            json={"article": {"id": a["id"], "body_html": new_body}})
        ok = r.status_code in (200, 201)
        done += int(ok)
        print(f"    {'✅ written' if ok else '❌ failed ' + str(r.status_code)}")

    if APPLY:
        print(f"\n✓ {done}/{len(todo)} articles updated.")
    elif todo:
        print("\nDRY-RUN — nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main()
