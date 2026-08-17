#!/usr/bin/env python3
"""
Published articles the bot does not know about.

WHY
data/content_state.json is the bot's index of its own content: content_retrofit,
ctr_optimizer, legal_watchdog and the Reddit article matcher all iterate over it.
An article missing from it is not merely unlisted — it is never retrofitted, never
CTR-tuned, never legally re-checked, and can never be linked as a source.

The gap surfaced on 2026-08-17: replace_ai_covers.py reported 12 articles with an
AI cover where the og:image sweep over content_state.json had found 11. Shopify
was right and the index was short, so the extra article had been carrying an AI
cover with nobody counting it.

Usage:
  python3 scripts/untracked_articles.py
"""
import json
import os
import subprocess
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _ensure_shopify_token() -> None:
    """Must run before seo_bot is imported — it reads the token at import time."""
    if os.getenv("SHOPIFY_TOKEN"):
        return
    try:
        tok = subprocess.run([sys.executable, os.path.join(ROOT, "mint_shopify_token.py")],
                             capture_output=True, text=True, timeout=45).stdout.strip()
    except Exception as e:
        tok, _ = "", print(f"   ⚠️  Token-Prägung fehlgeschlagen: {str(e)[:70]}")
    if tok:
        os.environ["SHOPIFY_TOKEN"] = tok
        print(f"   ✓ Shopify-Token geprägt ({tok[:6]}…)")


_ensure_shopify_token()

from seo_bot import BLOG_ID, SHOPIFY_HEADERS, SHOPIFY_STORE  # noqa: E402

API = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
STATE = os.path.join(ROOT, "data", "content_state.json")


def main() -> None:
    try:
        with open(STATE, encoding="utf-8") as f:
            arts = (json.load(f) or {}).get("articles") or {}
    except Exception as e:
        print(f"⛔ content_state.json nicht lesbar: {e}")
        return
    known = {u.rstrip("/").rsplit("/", 1)[-1] for u in arts}

    live, url = [], (f"{API}/blogs/{BLOG_ID}/articles.json"
                     "?fields=id,title,handle,image&limit=250&published_status=published")
    try:
        while url:
            r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
            r.raise_for_status()
            live.extend(r.json().get("articles", []))
            url = next((p.split(";")[0].strip(" <>")
                        for p in r.headers.get("Link", "").split(",")
                        if 'rel="next"' in p), None)
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", 0)
        print("⛔ Shopify lehnt den Zugriff ab (401/403):\n"
              '     export SHOPIFY_TOKEN="$(python3 mint_shopify_token.py)"'
              if code in (401, 403) else f"⛔ Shopify-API: {str(e)[:110]}")
        return

    missing = [a for a in live if a.get("handle") not in known]
    print(f"\nShopify: {len(live)} veröffentlichte Artikel · "
          f"content_state.json: {len(known)}\n")
    if not missing:
        print("✅ Der Bot kennt jeden veröffentlichten Artikel.")
        return

    print(f"⚠️  {len(missing)} Artikel fehlen im Bestand des Bots — sie werden weder "
          f"nachoptimiert noch rechtlich nachgeprüft:\n")
    for a in missing:
        print(f"  https://{'velluto-shop.com'}/blogs/velluto-the-magazine/{a['handle']}")
        cover = ((a.get("image") or {}).get("src") or "").rsplit("/", 1)[-1].split("?")[0]
        print(f"     Titel: {a.get('title', '')[:78]}")
        print(f"     Cover: {cover or '— keins'}\n")
    print("Sie kommen in den Bestand, sobald blog_review.py bzw. der nächste "
          "run.sh-Durchlauf sie einliest.")


if __name__ == "__main__":
    main()
