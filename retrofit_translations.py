"""
Velluto SEO — Retrofit Translations
====================================
One-time script to add missing locale translations to all published articles
that were created before the 11-locale expansion.

Usage:
  python3 retrofit_translations.py --dry-run   # inspect only
  python3 retrofit_translations.py              # apply

Cost: ~$0.025 per locale × missing locales per article ≈ $5 total
"""

import argparse
import json
import os
import sys
import time

import requests

# ── Config ──────────────────────────────────────────────────────────────────
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID       = os.getenv("BLOG_ID", "127785959765")
SHOPIFY_HEADERS = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json",
}

# Load these from seo_bot so we stay DRY
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seo_bot import (
    SHOP_LOCALES,
    generate_market_adaptation,
    get_translatable_digests,
    register_shopify_translation,
    research_market_keywords,
)

RATE_LIMIT_DELAY = 8   # seconds between articles (Shopify + Anthropic rate limits)

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_all_articles() -> list[dict]:
    arts = []
    page_info = None
    while True:
        params = {"limit": 250, "fields": "id,title,handle,body_html,published_at"}
        if page_info:
            params["page_info"] = page_info
        r = requests.get(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json",
            params=params, headers=SHOPIFY_HEADERS, timeout=20,
        )
        data = r.json().get("articles", [])
        arts.extend(data)
        link = r.headers.get("Link", "")
        if 'rel="next"' in link:
            import re
            m = re.search(r'page_info=([^&>]+).*rel="next"', link)
            page_info = m.group(1) if m else None
            if not page_info:
                break
        else:
            break
    return arts


def get_existing_translation_locales(article_id: int) -> set[str]:
    """Return set of locale codes that already have translations registered."""
    gid = f"gid://shopify/Article/{article_id}"
    query = """
    query($id: ID!) {
      translatableResource(resourceId: $id) {
        translations(locale: "") { locale }
      }
    }
    """
    # The above query syntax is wrong for getting all translations.
    # Use a different approach: check each locale via translatableResource.
    # Actually easier: just get the digests and try registering only if missing.
    # Use the translations endpoint.
    r = requests.post(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
        headers=SHOPIFY_HEADERS,
        json={"query": f"""
        {{
          translatableResource(resourceId: "gid://shopify/Article/{article_id}") {{
            translations(locale: "") {{ locale key }}
          }}
        }}
        """},
        timeout=20,
    )
    data = r.json().get("data", {})
    translations = (
        (data.get("translatableResource") or {})
        .get("translations", [])
    )
    return {t["locale"] for t in translations}


def get_translation_keys_by_locale(article_id: int) -> dict[str, set[str]]:
    """Return {locale: {translated keys}} for an article.

    A locale that has a body_html translation but no `title` translation will
    render with a German/localized body and an English (primary) title — the
    exact symptom we're repairing. Tracking keys per locale (not just which
    locales exist) lets us detect and fix those partial translations."""
    r = requests.post(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
        headers=SHOPIFY_HEADERS,
        json={"query": """
        query($id: ID!) {
          translatableResource(resourceId: $id) {
            translations(locale: "") { locale key }
          }
        }
        """,
        "variables": {"id": f"gid://shopify/Article/{article_id}"}},
        timeout=20,
    )
    data = r.json().get("data", {})
    items = ((data.get("translatableResource") or {}).get("translations") or [])
    by_locale: dict[str, set[str]] = {}
    for t in items:
        by_locale.setdefault(t["locale"], set()).add(t["key"])
    return by_locale


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Inspect only, no API writes")
    parser.add_argument("--article-id", type=int, help="Process only this article ID")
    args = parser.parse_args()

    print("🔧 Velluto Retrofit Translations")
    print(f"   Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"   Target locales: {SHOP_LOCALES}\n")

    articles = get_all_articles()
    print(f"   Found {len(articles)} published articles\n")

    if args.article_id:
        articles = [a for a in articles if a["id"] == args.article_id]
        print(f"   Filtered to article {args.article_id}\n")

    total_adaptations = 0
    total_cost_estimate = 0.0

    for i, article in enumerate(articles):
        aid = article["id"]
        handle = article["handle"]
        title = article["title"]
        body_html = article.get("body_html", "")

        print(f"[{i+1}/{len(articles)}] {handle}")

        # Only process bot articles (contain .vl class)
        if 'class="vl"' not in body_html:
            print(f"   ⏭  Not a bot article (no .vl class) — skipping")
            continue

        # Get existing translations, keyed per locale so we can detect locales
        # that are translated but MISSING the title (body localized, title still EN).
        keys_by_locale = get_translation_keys_by_locale(aid)
        existing_locales = set(keys_by_locale)
        # A locale needs (re)processing if it has no translation at all, OR it has
        # a body translation but no `title` translation.
        missing_locales = [
            loc for loc in SHOP_LOCALES
            if "title" not in keys_by_locale.get(loc, set())
        ]
        title_only_repairs = [
            loc for loc in missing_locales if loc in existing_locales
        ]

        if not missing_locales:
            print(f"   ✅ All {len(SHOP_LOCALES)} locales have a title translation")
            continue

        print(f"   Existing: {sorted(existing_locales) or 'none'}")
        print(f"   Needs title: {missing_locales}")
        if title_only_repairs:
            print(f"   ↻ Title-missing (body already localized): {title_only_repairs}")

        if args.dry_run:
            est = len(missing_locales) * 0.025
            total_cost_estimate += est
            total_adaptations += len(missing_locales)
            print(f"   [DRY RUN] Would generate {len(missing_locales)} adaptations (~${est:.2f})")
            continue

        # Research market keywords for this article's keyword
        # Use article title as the DE keyword hint
        de_kw_hint = handle.replace("-", " ")
        print(f"   Researching market keywords for: {de_kw_hint[:50]}...")
        try:
            mkt_kws = research_market_keywords(de_kw_hint)
        except Exception as e:
            print(f"   ⚠️  Keyword research failed: {e} — using handle as fallback")
            mkt_kws = {loc: {"keyword": de_kw_hint, "intent": ""} for loc in SHOP_LOCALES}
            mkt_kws["de"] = {"keyword": de_kw_hint, "intent": ""}

        # Fetch digests — wait for title so the title translation is never skipped
        try:
            digests = get_translatable_digests(aid, require_keys=("title", "body_html"))
        except Exception as e:
            print(f"   ⚠️  Could not fetch digests: {e} — skipping article")
            continue

        # Build a minimal post dict for generate_market_adaptation
        post = {"body_html": body_html, "title_de": title}

        # Generate + register each missing locale
        for locale in missing_locales:
            market = mkt_kws.get(locale, {"keyword": de_kw_hint, "intent": ""})
            print(f"   [{locale}] Adapting (kw: {market['keyword'][:40]})...")
            try:
                adaptation = generate_market_adaptation(post, locale, market)
                ok = register_shopify_translation(
                    aid, locale,
                    adaptation["title"],
                    adaptation["body_html"],
                    adaptation["meta_desc"],
                    digests,
                )
                status = "✅" if ok else "❌"
                print(f"   {status} [{locale}] {adaptation['title'][:50]}")
                total_adaptations += 1
                total_cost_estimate += 0.025
            except Exception as e:
                print(f"   ❌ [{locale}] Error: {e}")

            time.sleep(2)  # small delay between locale calls

        print(f"   Done. Sleeping {RATE_LIMIT_DELAY}s...\n")
        time.sleep(RATE_LIMIT_DELAY)

    print(f"\n{'='*50}")
    print(f"{'[DRY RUN] ' if args.dry_run else ''}Done!")
    print(f"Total adaptations: {total_adaptations}")
    print(f"Estimated cost: ~${total_cost_estimate:.2f}")
    if args.dry_run:
        print("\nRun without --dry-run to apply.")


if __name__ == "__main__":
    main()
