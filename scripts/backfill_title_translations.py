#!/usr/bin/env python3
"""
One-off: re-translate articles whose locale translation failed (title is blank or
still the English title — the symptom of the old "one blank field rejects the whole
batch" bug, which left title AND body in English for that locale).

For each such locale it re-runs the SAME adaptation the daily pipeline uses
(generate_market_adaptation → title + meta + body, with per-market pricing) and
re-registers it via the now-fixed register_shopify_translation (skips blank values).

Locales whose title is already localized are left untouched (idempotent). EN is the
primary locale and is never a target. Dry-run by default; pass --apply to write.

Usage:
  python3 scripts/backfill_title_translations.py            # dry-run (lists work)
  python3 scripts/backfill_title_translations.py --apply     # re-translate + register
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from seo_bot import (
    SHOPIFY_STORE, SHOPIFY_HEADERS, BLOG_ID, SHOP_LOCALES,
    get_translatable_digests, register_shopify_translation,
    generate_market_adaptation, graphql_with_vars,
)
from commercial_config import load_commercial_config

APPLY = "--apply" in sys.argv


def _list_articles() -> list[dict]:
    out, url = [], (
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        "?fields=id,title,handle,body_html,tags&limit=250"
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


def _needs_fix(cur_title: str, en_title: str) -> bool:
    cur = (cur_title or "").strip().lower()
    en  = (en_title or "").strip().lower()
    return (not cur) or (cur == en)   # missing OR still the English title


def main():
    print(f"=== backfill_title_translations.py [{'APPLY' if APPLY else 'DRY-RUN'}] ===\n")
    commercial = None
    try:
        commercial = load_commercial_config()
    except Exception as e:
        print(f"   ⚠️  commercial config unavailable ({e}) — prices won't be re-localized")

    articles = _list_articles()
    print(f"{len(articles)} articles in blog {BLOG_ID}\n")

    fixed = skipped_ok = 0
    for a in articles:
        aid, en_title, en_body = a["id"], a.get("title", ""), a.get("body_html", "")
        kw = (a.get("tags", "").split(",")[0].strip() or en_title)
        de_post = {"title": en_title, "meta_description": "",
                   "body_html": en_body, "keyword": kw}

        digests = None
        for loc in SHOP_LOCALES:
            tx = _read_translation(aid, loc)
            if not _needs_fix(tx.get("title", ""), en_title):
                skipped_ok += 1
                continue
            print(f"[{loc}] '{en_title[:50]}' (#{aid}) — title missing/English → re-translate")
            fixed += 1
            if not APPLY:
                continue
            try:
                adap = generate_market_adaptation(de_post, loc, {"keyword": kw, "intent": ""},
                                                  commercial=commercial)
                if digests is None:
                    digests = get_translatable_digests(aid)
                ok = register_shopify_translation(
                    aid, loc, adap["title"], adap["body_html"], adap["meta_desc"], digests)
                print(f"     {'✅ ' + adap['title'][:60] if ok else '❌ register failed'}")
            except Exception as e:
                print(f"     ❌ {e}")

    print("\n=== Summary ===")
    print(f"Locale translations {'fixed' if APPLY else 'to fix'}: {fixed}")
    print(f"Already localized (skipped):           {skipped_ok}")
    if not APPLY:
        print("\nDRY-RUN — no changes written. Re-run with --apply to re-translate.")


if __name__ == "__main__":
    main()
