#!/usr/bin/env python3
"""
Deploy Velluto Magazin theme files to Shopify.
Uploads: CSS asset, Liquid section, article template JSON.

Usage:
  python3 scripts/deploy_theme.py              # deploy to edit theme (fallback ID below)
  python3 scripts/deploy_theme.py --live       # deploy to the CURRENTLY PUBLISHED theme
  python3 scripts/deploy_theme.py --theme-id 123456789  # specific theme

--live resolves the published theme via the API (role == "main") at runtime.
Theme IDs change whenever a new theme is published, so a hardcoded live ID
would silently deploy into the OLD theme — that bit us after the Jul 2026
theme relaunch, hence the dynamic lookup. The script aborts if the lookup
fails rather than falling back to a possibly-stale ID.
"""

import os, sys, json, requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SHOP    = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
TOKEN   = os.getenv("SHOPIFY_TOKEN")
API_VER = "2024-10"

EDIT_THEME_ID = "198208389461"   # "Velluto Update 06/2026" — safe to edit

THEME_DIR = Path(__file__).parent.parent / "theme"

FILES = [
    ("assets/velluto-magazine.css",                           THEME_DIR / "assets/velluto-magazine.css"),
    ("sections/velluto-magazine-article.liquid",              THEME_DIR / "sections/velluto-magazine-article.liquid"),
    ("templates/article.velluto-magazine.json",               THEME_DIR / "templates/article.velluto-magazine.json"),
]

def resolve_live_theme() -> tuple[str, str]:
    """(id, name) of the currently PUBLISHED theme (role == "main")."""
    r = requests.get(
        f"https://{SHOP}/admin/api/{API_VER}/themes.json",
        headers={"X-Shopify-Access-Token": TOKEN}, timeout=20)
    if r.status_code != 200:
        print(f"Error: could not list themes ({r.status_code}): {r.text[:200]}")
        sys.exit(1)
    for t in r.json().get("themes", []):
        if t.get("role") == "main":
            return str(t["id"]), t.get("name", "?")
    print("Error: no published (role=main) theme found")
    sys.exit(1)


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
        label = f"theme {theme_id}"
    elif use_live:
        theme_id, name = resolve_live_theme()
        label = f'LIVE "{name}" (#{theme_id})'
    else:
        theme_id = EDIT_THEME_ID
        label = f"edit theme {theme_id}"

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
