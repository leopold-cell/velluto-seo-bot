#!/usr/bin/env python3
"""
One-time backfill: localized SEO meta_description (+ title) for EXISTING articles.

Fixes the historical gap where non-EN markets showed the ENGLISH SERP snippet
(the bot used to register the meta under the wrong key `summary_html` instead of
Shopify's real translatable key `meta_description`).

SAFE BY DESIGN:
  - Only registers `meta_description` (and, unless --meta-only, `title`).
  - Does NOT touch `body_html` — existing localized article bodies stay exactly as is.
  - Idempotent: re-running just re-registers the same keys with fresh digests.

Usage (run on the VPS, where SHOPIFY_TOKEN + ANTHROPIC_API_KEY live in .env):
  python3 scripts/backfill_translations.py --dry-run            # preview, no writes
  python3 scripts/backfill_translations.py --limit 2            # do 2 articles for real
  python3 scripts/backfill_translations.py                      # full backfill
  python3 scripts/backfill_translations.py --meta-only          # only meta, never touch title
"""
import argparse
import json
import os
import re
import sys
import time

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"), override=True)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "")
BLOG_ID       = os.getenv("BLOG_ID", "")
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
API = f"https://{SHOPIFY_STORE}/admin/api/2024-01"

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL  = "claude-haiku-4-5-20251001"

# Mirrors seo_bot.SHOP_LOCALES exactly (kept local so this script is self-contained).
SHOP_LOCALES = ["de", "nl", "fr", "es", "it", "da", "nb", "pl", "pt-PT", "sv"]
LANG_NAMES = {
    "de": "German", "nl": "Dutch", "fr": "French", "es": "Spanish", "it": "Italian",
    "da": "Danish", "nb": "Norwegian Bokmal", "pl": "Polish", "pt-PT": "Portuguese",
    "sv": "Swedish",
}


def gql(query: str, variables: dict | None = None) -> dict:
    r = requests.post(f"{API}/graphql.json", headers=HEADERS,
                      json={"query": query, "variables": variables or {}}, timeout=30)
    return r.json().get("data", {}) or {}


def fetch_articles() -> list[dict]:
    """All articles in the blog (REST, paginated). Returns [{id, title, handle}]."""
    out, url = [], (f"{API}/blogs/{BLOG_ID}/articles.json?fields=id,title,handle&limit=250")
    while url:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        nxt = None
        for part in r.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                nxt = part.split(";")[0].strip(" <>")
        url = nxt
    return out


def en_content(article_id: int) -> tuple[dict, dict]:
    """Return ({key: EN value}, {key: digest}) from the article's translatable content."""
    gid = f"gid://shopify/Article/{article_id}"
    data = gql("""
      query($id: ID!) {
        translatableResource(resourceId: $id) {
          translatableContent { key value digest }
        }
      }""", {"id": gid})
    items = (data.get("translatableResource") or {}).get("translatableContent", []) or []
    values  = {i["key"]: i.get("value", "") for i in items}
    digests = {i["key"]: i["digest"] for i in items if i.get("digest")}
    return values, digests


def derive_keyword(title: str) -> str:
    t = re.split(r"[|:]", title or "")[0].strip()
    return " ".join(t.split()[:7]) or title


def adapt_title_meta(en_title: str, en_meta: str, lang_name: str, keyword: str) -> dict:
    r = client.messages.create(
        model=MODEL, max_tokens=250,
        system="Return ONLY valid JSON, no extra text.",
        messages=[{"role": "user", "content":
            f"Localize these for the {lang_name} market. Keyword: '{keyword}'.\n"
            f"EN title: {en_title}\nEN meta: {en_meta}\n\n"
            f"Rules: write ENTIRELY in {lang_name}; lead with the keyword; brand 'Velluto' "
            f"after the keyword; no em-dash/en-dash.\n"
            f"Return: {{\"title\": \"<max 60 chars in {lang_name}>\", "
            f"\"meta\": \"<140-155 chars in {lang_name}>\"}}"
        }])
    raw = r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    try:
        d = json.loads(raw)
        return {"title": (d.get("title") or keyword)[:60], "meta": (d.get("meta") or "")[:155]}
    except Exception:
        return {"title": keyword[:60], "meta": en_meta[:155]}


def register(article_id: int, locale: str, fields: dict, digests: dict) -> bool:
    """Register ONLY the given keys for one locale. Never sends body_html."""
    gid = f"gid://shopify/Article/{article_id}"
    translations = []
    for key, value in fields.items():
        dg = digests.get(key)
        if not dg or not value:
            continue
        translations.append({"key": key, "value": value,
                             "translatableContentDigest": dg, "locale": locale})
    if not translations:
        return False
    data = gql("""
      mutation register($resourceId: ID!, $translations: [TranslationInput!]!) {
        translationsRegister(resourceId: $resourceId, translations: $translations) {
          userErrors { field message }
        }
      }""", {"resourceId": gid, "translations": translations})
    errs = (data.get("translationsRegister") or {}).get("userErrors", []) or []
    errs = [e for e in errs if "primary locale" not in (e.get("message", "").lower())]
    if errs:
        print(f"      ⚠️  [{locale}] {errs}")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="preview only, no writes")
    ap.add_argument("--limit", type=int, default=0, help="process only N articles")
    ap.add_argument("--meta-only", action="store_true", help="only meta_description, never title")
    args = ap.parse_args()

    if not (SHOPIFY_TOKEN and SHOPIFY_STORE and BLOG_ID):
        print("❌ Missing SHOPIFY_TOKEN / SHOPIFY_STORE / BLOG_ID in .env"); sys.exit(1)

    arts = fetch_articles()
    if args.limit:
        arts = arts[:args.limit]
    print(f"🌍 Backfill localized meta{'' if args.meta_only else '+title'} for "
          f"{len(arts)} articles × {len(SHOP_LOCALES)} locales "
          f"{'(DRY RUN)' if args.dry_run else ''}\n")

    done = failed = skipped = 0
    for n, a in enumerate(arts, 1):
        aid, title = a["id"], a.get("title", "")
        print(f"[{n}/{len(arts)}] {title[:60]} (#{aid})")
        try:
            values, digests = en_content(aid)
        except Exception as e:
            print(f"   ⚠️  content fetch failed: {e}"); failed += 1; continue
        if "meta_description" not in digests:
            print("   · no translatable meta_description on this article — skipping")
            skipped += 1; continue
        en_title = values.get("title", title)
        en_meta  = values.get("meta_description", "")
        kw = derive_keyword(en_title)

        for locale in SHOP_LOCALES:
            tm = adapt_title_meta(en_title, en_meta, LANG_NAMES.get(locale, locale), kw)
            fields = {"meta_description": tm["meta"]}
            if not args.meta_only:
                fields["title"] = tm["title"]
            if args.dry_run:
                print(f"   [{locale}] meta → {tm['meta']}")
                if not args.meta_only:
                    print(f"   [{locale}] title→ {tm['title']}")
                continue
            ok = register(aid, locale, fields, digests)
            print(f"   [{locale}] {'✓' if ok else '✗'} {tm['meta'][:70]}")
            done += ok
            time.sleep(0.4)  # Shopify rate limit

    print(f"\n✅ Backfill complete — {done} locale-registrations written, "
          f"{skipped} articles skipped, {failed} fetch failures"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
