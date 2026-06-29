#!/usr/bin/env python3
"""
One-off: fix "alternatives to <Brand>" articles whose comparison table lists the
SAME competitor brand more than once (e.g. an Oakley-alternatives post that has
two Oakley rows). Keeps ONE brand row as the reference baseline, drops the extras.

Operates on every article whose title frames it as alternatives to a competitor
(detected via briefs.quality_gate.alternatives_target_brand) — EN body + every
locale translation (brand names aren't translated, so the same rule applies).
Rows are only removed, never added; no specs are fabricated. Idempotent.
Dry-run by default; pass --apply to write.

Usage:
  python3 scripts/fix_alternatives_table.py            # dry-run
  python3 scripts/fix_alternatives_table.py --apply     # write
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from seo_bot import (
    SHOPIFY_STORE, SHOPIFY_HEADERS, BLOG_ID, SHOP_LOCALES,
    get_translatable_digests, graphql_with_vars,
)
from briefs.quality_gate import alternatives_target_brand, limit_brand_table_rows

APPLY = "--apply" in sys.argv


def _register_body_translation(aid: int, locale: str, body_html: str, digests: dict) -> bool:
    """Register ONLY the body_html translation (we change just the table, so we must
    not touch title/meta — sending blank values for those is what Shopify rejects)."""
    digest = digests.get("body_html", "")
    if not digest:
        print(f"   ⚠️  [{locale}] no body_html digest — skipped")
        return False
    mutation = """
    mutation translationsRegister($resourceId: ID!, $translations: [TranslationInput!]!) {
      translationsRegister(resourceId: $resourceId, translations: $translations) {
        userErrors { field message }
        translations { key }
      }
    }"""
    res = graphql_with_vars(mutation, {
        "resourceId": f"gid://shopify/Article/{aid}",
        "translations": [{"key": "body_html", "value": body_html,
                          "translatableContentDigest": digest, "locale": locale}],
    })
    errs = (res.get("translationsRegister") or {}).get("userErrors", [])
    if errs:
        if any("primary locale" in e.get("message", "").lower() for e in errs):
            return True  # this locale is the shop default — not a failure
        print(f"   ⚠️  [{locale}] {errs}")
        return False
    return True


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
    print(f"=== fix_alternatives_table.py [{'APPLY' if APPLY else 'DRY-RUN'}] ===\n")
    articles = _list_articles()
    print(f"{len(articles)} articles in blog {BLOG_ID}\n")

    fixed_en = fixed_tx = 0
    for a in articles:
        aid, title, body = a["id"], a.get("title", ""), a.get("body_html", "")
        brand = alternatives_target_brand(title)
        if not brand:
            continue

        new_body, n = limit_brand_table_rows(body, brand)
        if n:
            print(f"[EN] '{title[:55]}' (#{aid}) — removed {n} extra {brand} row(s)")
            if APPLY:
                print(f"     {'✅ updated' if _update_en_body(aid, new_body) else '❌ failed'}")
            fixed_en += 1

        digests = None
        for loc in SHOP_LOCALES:
            tx = _read_translation(aid, loc)
            new_tx, n = limit_brand_table_rows(tx.get("body_html", ""), brand)
            if not n:
                continue
            print(f"[{loc}] '{title[:45]}' (#{aid}) — removed {n} extra {brand} row(s)")
            if APPLY:
                if digests is None:
                    digests = get_translatable_digests(aid)
                ok = _register_body_translation(aid, loc, new_tx, digests)
                print(f"     {'✅ re-registered' if ok else '❌ failed'}")
            fixed_tx += 1

    print("\n=== Summary ===")
    print(f"EN bodies fixed:            {fixed_en}")
    print(f"Locale translations fixed:  {fixed_tx}")
    if not APPLY:
        print("\nDRY-RUN — no changes written. Re-run with --apply to fix.")


if __name__ == "__main__":
    main()
