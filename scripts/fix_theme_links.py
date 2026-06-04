#!/usr/bin/env python3
"""
Audit + fix absolute INTERNAL links in the live Shopify theme so they become
root-relative (/products/..., /collections/..., /pages/..., /, ...).

Why: internal storefront links should be root-relative. Absolute links like
`href="https://velluto-shop.com/collections/..."` break locale handling and add
needless redirects. Required-absolute tags (canonical, hreflang, og:url,
JSON-LD) and CDN asset URLs are deliberately LEFT UNTOUCHED.

This complements scripts/deploy_theme.py — same Shopify Asset REST API, same
theme IDs and SHOPIFY_TOKEN from .env. The theme files are NOT stored in this
repo, so this script pulls each liquid/json asset, scans/rewrites in memory,
and (with --apply) PUTs the fixed version back.

Usage:
  python3 scripts/fix_theme_links.py                 # DRY-RUN, edit theme (198208389461)
  python3 scripts/fix_theme_links.py --apply         # write fixes to edit theme
  python3 scripts/fix_theme_links.py --live          # DRY-RUN against the LIVE theme
  python3 scripts/fix_theme_links.py --live --apply  # write fixes to the LIVE theme
  python3 scripts/fix_theme_links.py --theme-id 123  # specific theme

Recommended flow: run on the EDIT theme with --apply, eyeball it in the Shopify
theme editor / preview, then re-run with --live --apply.
"""

import os, re, sys, requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SHOP    = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
TOKEN   = os.getenv("SHOPIFY_TOKEN")
API_VER = "2024-10"

EDIT_THEME_ID = "198208389461"   # "Velluto Update 06/2026" — safe to edit
LIVE_THEME_ID = "197496209749"   # live theme — careful

DOMAIN = "velluto-shop.com"

# Only audit text-based theme files that can contain markup links.
SCAN_PREFIXES = ("sections/", "snippets/", "templates/", "blocks/", "layout/")
SCAN_SUFFIXES = (".liquid", ".json")

# Lines containing any of these are required-absolute or non-page assets —
# never rewrite them.
SKIP_LINE_MARKERS = (
    "canonical", "hreflang", 'rel="alternate"', "rel='alternate'",
    "og:url", "og:image", "twitter:", "application/ld+json", '"@context"',
    "/cdn/", "preconnect", "dns-prefetch",
)

# Match absolute internal links inside attribute quotes only (href/action/etc.),
# capturing the path so we can drop the scheme+host. Both https:// and
# protocol-relative //domain forms, optional www.
LINK_RE = re.compile(
    r'(?P<attr>\b(?:href|action|formaction)\s*=\s*["\'])'
    r'(?:https?:)?//(?:www\.)?' + re.escape(DOMAIN) +
    r'(?P<path>/[^"\']*)?(?P<q>["\'])'
)


def _headers():
    return {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}


def list_assets(theme_id: str) -> list[str]:
    url = f"https://{SHOP}/admin/api/{API_VER}/themes/{theme_id}/assets.json"
    r = requests.get(url, headers=_headers(), timeout=30)
    r.raise_for_status()
    keys = [a["key"] for a in r.json().get("assets", [])]
    return [
        k for k in keys
        if k.startswith(SCAN_PREFIXES) and k.endswith(SCAN_SUFFIXES)
    ]


def get_asset(theme_id: str, key: str) -> str | None:
    url = f"https://{SHOP}/admin/api/{API_VER}/themes/{theme_id}/assets.json"
    r = requests.get(url, headers=_headers(), params={"asset[key]": key}, timeout=30)
    if r.status_code != 200:
        print(f"  ! could not read {key} ({r.status_code})")
        return None
    return (r.json().get("asset") or {}).get("value")


def put_asset(theme_id: str, key: str, value: str) -> bool:
    url = f"https://{SHOP}/admin/api/{API_VER}/themes/{theme_id}/assets.json"
    payload = {"asset": {"key": key, "value": value}}
    r = requests.put(url, headers=_headers(), json=payload, timeout=30)
    return r.status_code in (200, 201)


def fix_text(text: str) -> tuple[str, list[str]]:
    """Rewrite absolute internal links to root-relative, line by line, skipping
    required-absolute / asset lines. Returns (new_text, list_of_changes)."""
    changes: list[str] = []
    out_lines = []
    for line in text.splitlines(keepends=True):
        low = line.lower()
        if any(m.lower() in low for m in SKIP_LINE_MARKERS):
            out_lines.append(line)
            continue
        if not LINK_RE.search(line):
            out_lines.append(line)
            continue

        def _repl(m: re.Match) -> str:
            path = m.group("path") or "/"
            changes.append(f"{m.group(0)}  ->  {m.group('attr')}{path}{m.group('q')}")
            return f"{m.group('attr')}{path}{m.group('q')}"

        out_lines.append(LINK_RE.sub(_repl, line))
    return "".join(out_lines), changes


def main():
    if not TOKEN:
        print("Error: SHOPIFY_TOKEN not set in .env"); sys.exit(1)

    apply   = "--apply" in sys.argv
    use_live = "--live" in sys.argv
    custom_idx = next((i for i, a in enumerate(sys.argv) if a == "--theme-id"), None)
    if custom_idx:
        theme_id = sys.argv[custom_idx + 1]
    elif use_live:
        theme_id = LIVE_THEME_ID
    else:
        theme_id = EDIT_THEME_ID

    label = "LIVE" if theme_id == LIVE_THEME_ID else f"theme {theme_id}"
    mode  = "APPLY" if apply else "DRY-RUN"
    print(f"\n=== fix_theme_links.py [{mode}] → {SHOP} ({label}) ===\n")

    keys = list_assets(theme_id)
    print(f"Scanning {len(keys)} liquid/json assets…\n")

    total_changes = files_changed = 0
    for key in keys:
        text = get_asset(theme_id, key)
        if not text:
            continue
        new_text, changes = fix_text(text)
        if not changes:
            continue
        files_changed += 1
        total_changes += len(changes)
        print(f"[{key}] — {len(changes)} absolute internal link(s):")
        for c in changes:
            print(f"    {c}")
        if apply:
            ok = put_asset(theme_id, key, new_text)
            print(f"    {'✅ updated' if ok else '❌ FAILED to update'}")
        print()

    print(f"--- {total_changes} link(s) across {files_changed} file(s) "
          f"{'rewritten' if apply else 'would be rewritten (dry-run)'} ---")
    if not apply and total_changes:
        print("Re-run with --apply to write the changes.")


if __name__ == "__main__":
    main()
