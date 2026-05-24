#!/usr/bin/env python3
"""
Deploy Velluto Magazin theme files to Shopify.
Uploads: CSS asset, Liquid section, article template JSON.

Usage:
  python3 scripts/deploy_theme.py              # deploy to edit theme (198208389461)
  python3 scripts/deploy_theme.py --live       # deploy to live theme (197496209749)
  python3 scripts/deploy_theme.py --theme-id 123456789  # specific theme
"""

import os, sys, json, requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SHOP    = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
TOKEN   = os.getenv("SHOPIFY_TOKEN")
API_VER = "2024-10"

EDIT_THEME_ID = "198208389461"   # "Velluto Update 06/2026" — safe to edit
LIVE_THEME_ID = "197496209749"   # live theme — careful

THEME_DIR = Path(__file__).parent.parent / "theme"

FILES = [
    ("assets/velluto-magazine.css",                           THEME_DIR / "assets/velluto-magazine.css"),
    ("sections/velluto-magazine-article.liquid",              THEME_DIR / "sections/velluto-magazine-article.liquid"),
    ("templates/article.velluto-magazine.json",               THEME_DIR / "templates/article.velluto-magazine.json"),
]

def upload(theme_id: str, key: str, path: Path):
    url = f"https://{SHOP}/admin/api/{API_VER}/themes/{theme_id}/assets.json"
    headers = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
    payload = {"asset": {"key": key, "value": path.read_text(encoding="utf-8")}}
    r = requests.put(url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"  ✓  {key}")
    else:
        print(f"  ✗  {key}  →  {r.status_code}: {r.text[:200]}")
        sys.exit(1)

def main():
    if not TOKEN:
        print("Error: SHOPIFY_TOKEN not set in .env"); sys.exit(1)

    use_live   = "--live" in sys.argv
    custom_idx = next((i for i, a in enumerate(sys.argv) if a == "--theme-id"), None)
    if custom_idx:
        theme_id = sys.argv[custom_idx + 1]
    elif use_live:
        theme_id = LIVE_THEME_ID
    else:
        theme_id = EDIT_THEME_ID

    label = "LIVE" if theme_id == LIVE_THEME_ID else f"theme {theme_id}"
    print(f"\nDeploying Velluto Magazin → {SHOP} ({label})\n")

    for key, path in FILES:
        if not path.exists():
            print(f"  ✗  Missing: {path}"); sys.exit(1)
        upload(theme_id, key, path)

    print(f"""
Done. Next steps:
  1. Open Shopify Admin → Online Store → Themes → "{label}"
  2. Customize → find an article → switch template to "velluto-magazine"
  3. Configure section settings (author bio, sticky CTA product, etc.)
  4. When ready: publish the theme (or copy the template to the live theme)
""")

if __name__ == "__main__":
    main()
