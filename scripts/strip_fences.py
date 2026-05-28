#!/usr/bin/env python3
"""
One-time cleanup: strip leaked ```html markdown fences from already-published
blog articles AND their T&A translations.

Background: before Phase 4.7, Sonnet sometimes wrapped the ===BODY=== output in
a ```html … ``` fence. _parse_primary_response captured it verbatim, so the
literal text '```html' appears at the top of the article body — and propagated
into every locale translation via Haiku.

This script:
  1. Lists all blog articles.
  2. For each, strips the fence from the EN body_html → REST update if changed.
  3. For each locale (DE/NL/FR/…), reads the current translation, strips the
     fence, re-registers via translationsRegister if changed.

Idempotent: articles/translations without a fence are skipped.
Dry-run by default — pass --apply to actually write.

Usage:
  python3 scripts/strip_fences.py            # dry-run (shows what would change)
  python3 scripts/strip_fences.py --apply    # actually fix
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from seo_bot import (
    SHOPIFY_STORE, SHOPIFY_HEADERS, BLOG_ID, SHOP_LOCALES,
    _strip_md_fence, get_translatable_digests, register_shopify_translation,
    graphql_with_vars,
)

APPLY = "--apply" in sys.argv


def _has_fence(html: str) -> bool:
    return "```" in (html or "")


def _list_articles() -> list[dict]:
    """All articles in the Velluto blog (id, title, body_html)."""
    out, url = [], (
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        "?fields=id,title,handle,body_html&limit=250"
    )
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=20)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        link = r.headers.get("Link", "")
        nxt = None
        for part in link.split(","):
            if 'rel="next"' in part:
                nxt = part.split(";")[0].strip(" <>")
        url = nxt
    return out


def _update_en_body(article_id: int, new_body: str) -> bool:
    r = requests.put(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{article_id}.json",
        headers=SHOPIFY_HEADERS,
        json={"article": {"id": article_id, "body_html": new_body}},
        timeout=20,
    )
    return r.status_code == 200


def _read_translation(article_id: int, locale: str) -> dict[str, str]:
    """Return {key: value} for the article's existing translation in `locale`."""
    gid = f"gid://shopify/Article/{article_id}"
    query = """
    query($id: ID!, $locale: String!) {
      translatableResource(resourceId: $id) {
        translations(locale: $locale) { key value }
      }
    }
    """
    data = graphql_with_vars(query, {"id": gid, "locale": locale})
    items = ((data.get("translatableResource") or {}).get("translations") or [])
    return {it["key"]: it["value"] for it in items}


def main():
    mode = "APPLY" if APPLY else "DRY-RUN"
    print(f"=== strip_fences.py [{mode}] ===\n")

    articles = _list_articles()
    print(f"{len(articles)} articles in blog {BLOG_ID}\n")

    fixed_en = 0
    fixed_tx = 0

    for a in articles:
        aid   = a["id"]
        title = a.get("title", "")
        body  = a.get("body_html", "")

        # ── EN body ──
        if _has_fence(body):
            new_body = _strip_md_fence(body)
            if new_body != body:
                print(f"[EN] '{title[:50]}' (#{aid}) — fence found")
                if APPLY:
                    ok = _update_en_body(aid, new_body)
                    print(f"     {'✅ updated' if ok else '❌ update failed'}")
                else:
                    print(f"     would strip {len(body) - len(new_body)} chars")
                fixed_en += 1

        # ── Locale translations ──
        digests = None
        for loc in SHOP_LOCALES:
            tx = _read_translation(aid, loc)
            tx_body = tx.get("body_html", "")
            if not _has_fence(tx_body):
                continue
            new_tx_body = _strip_md_fence(tx_body)
            if new_tx_body == tx_body:
                continue
            print(f"[{loc}] '{title[:40]}' (#{aid}) — fence in translation")
            if APPLY:
                if digests is None:
                    digests = get_translatable_digests(aid)
                ok = register_shopify_translation(
                    aid, loc,
                    title=_strip_md_fence(tx.get("title", "")),
                    body_html=new_tx_body,
                    meta_desc=_strip_md_fence(tx.get("summary_html", "")),
                    digests=digests,
                )
                print(f"     {'✅ re-registered' if ok else '❌ failed'}")
            else:
                print(f"     would strip {len(tx_body) - len(new_tx_body)} chars")
            fixed_tx += 1

    print(f"\n=== Summary ===")
    print(f"EN bodies with fence:        {fixed_en}")
    print(f"Locale translations w/ fence: {fixed_tx}")
    if not APPLY:
        print(f"\nDRY-RUN — no changes written. Re-run with --apply to fix.")
    else:
        print(f"\n✅ Applied. Reload the articles to verify.")


if __name__ == "__main__":
    main()
