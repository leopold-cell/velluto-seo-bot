#!/usr/bin/env python3
"""
One-time cleanup: replace broken internal-link URLs in already-published blog
articles AND their T&A translations.

Background: before Phase 4.9, the brief/config hardcoded two 404 targets:
  /products/strada-pro          → 404
  /collections/cycling-sunglasses → 404
The fix points everything at the real, published StradaPro collection:
  /collections/velluto-stradapro-cycling-glasses  (verified 200)

This script scans every blog article's EN body + each locale translation,
replaces the bad URLs, and re-saves (REST for EN, translationsRegister for
locales). Idempotent. Dry-run by default; pass --apply to write.

Usage:
  python3 scripts/fix_internal_links.py            # dry-run
  python3 scripts/fix_internal_links.py --apply     # fix
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from seo_bot import (
    SHOPIFY_STORE, SHOPIFY_HEADERS, BLOG_ID, SHOP_LOCALES,
    get_translatable_digests, register_shopify_translation, graphql_with_vars,
)

APPLY = "--apply" in sys.argv

GOOD = "https://velluto-shop.com/collections/velluto-stradapro-cycling-glasses"
# (bad_substring, replacement) — order matters; longer/more-specific first.
REPLACEMENTS = [
    ("https://velluto-shop.com/products/strada-pro",           GOOD),
    ("https://velluto-shop.com/collections/cycling-sunglasses", GOOD),
    ("/products/strada-pro",                                    "/collections/velluto-stradapro-cycling-glasses"),
    ("/collections/cycling-sunglasses",                         "/collections/velluto-stradapro-cycling-glasses"),
]


def _apply_replacements(html: str) -> tuple[str, int]:
    n = 0
    out = html or ""
    for bad, good in REPLACEMENTS:
        if bad in out:
            n += out.count(bad)
            out = out.replace(bad, good)
    return out, n


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


def _update_en_body(aid: int, body: str) -> bool:
    r = requests.put(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{aid}.json",
        headers=SHOPIFY_HEADERS,
        json={"article": {"id": aid, "body_html": body}},
        timeout=20,
    )
    return r.status_code == 200


def _read_translation(aid: int, locale: str) -> dict[str, str]:
    gid = f"gid://shopify/Article/{aid}"
    q = """
    query($id: ID!, $locale: String!) {
      translatableResource(resourceId: $id) {
        translations(locale: $locale) { key value }
      }
    }"""
    data = graphql_with_vars(q, {"id": gid, "locale": locale})
    items = ((data.get("translatableResource") or {}).get("translations") or [])
    return {it["key"]: it["value"] for it in items}


def main():
    print(f"=== fix_internal_links.py [{'APPLY' if APPLY else 'DRY-RUN'}] ===\n")
    articles = _list_articles()
    print(f"{len(articles)} articles in blog {BLOG_ID}\n")

    fixed_en = fixed_tx = 0
    for a in articles:
        aid, title, body = a["id"], a.get("title", ""), a.get("body_html", "")
        new_body, n = _apply_replacements(body)
        if n:
            print(f"[EN] '{title[:50]}' (#{aid}) — {n} bad link(s)")
            if APPLY:
                print(f"     {'✅ updated' if _update_en_body(aid, new_body) else '❌ failed'}")
            fixed_en += 1

        digests = None
        for loc in SHOP_LOCALES:
            tx = _read_translation(aid, loc)
            new_tx, n = _apply_replacements(tx.get("body_html", ""))
            if not n:
                continue
            print(f"[{loc}] '{title[:40]}' (#{aid}) — {n} bad link(s)")
            if APPLY:
                if digests is None:
                    digests = get_translatable_digests(aid)
                ok = register_shopify_translation(
                    aid, loc,
                    title=tx.get("title", ""),
                    body_html=new_tx,
                    meta_desc=tx.get("summary_html", ""),
                    digests=digests,
                )
                print(f"     {'✅ re-registered' if ok else '❌ failed'}")
            fixed_tx += 1

    print(f"\n=== Summary ===")
    print(f"EN bodies with bad links:        {fixed_en}")
    print(f"Locale translations with bad links: {fixed_tx}")
    if not APPLY:
        print("\nDRY-RUN — no changes written. Re-run with --apply to fix.")


if __name__ == "__main__":
    main()
