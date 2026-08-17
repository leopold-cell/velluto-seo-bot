#!/usr/bin/env python3
"""
Replace AI-generated cover images on published articles with real photographs.

WHY
Eight of the ten images filed in seo_bot.py as the "May 2026 outdoor shoot" are
not photographs. Six carry a C2PA manifest naming OpenAI gpt-image 2.0; _2 and
_10 were confirmed by hand, their metadata having been stripped so the file could
not testify either way. Only _1 and _4 came out of a camera. All eight left the
pool on 2026-08-17, which stops NEW articles from drawing them and does nothing
for the ones already published — and those are what the public sees.

Eleven articles carry such a cover. The six with a manifest still ship it from
our own CDN, so their AI origin is verifiable by anyone at
contentcredentials.org/verify — Art. 50(4) AI Act (image content that appears
authentic) and § 5a UWG (a photorealistic AI image suggesting a real riding
situation). Swapping the image settles both without a disclosure label.

WHAT IT PICKS
A camera-verified photo from the same visual category, so the page keeps its
look. Only images classified "photo" are eligible — never UNKNOWN, which would
risk swapping an AI image for another AI image and reporting success. Assignment
is round-robin so the eleven do not all end up with the same cover.

Dry-run by default. --apply writes.

Usage:
  python3 scripts/replace_ai_covers.py            # show what would change
  python3 scripts/replace_ai_covers.py --apply
"""
import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Token minting lives in seo_bot now — one place for all fifteen scripts that
# import it, instead of a copy in each. The local helper this file carried was
# the second such copy and is gone.
#
# HERO_WHITELIST, not WHITELIST: the latter still holds UI graphics
# (purplestats, offerpurple, visioneexplained) and images too small for a
# 1200x800 cover. Drawing from it would swap an AI photo for a stats chart.
from seo_bot import (BLOG_ID, HERO_WHITELIST, SHOPIFY_HEADERS,  # noqa: E402
                     SHOPIFY_STORE)

API = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
INVENTORY = os.path.join(ROOT, "data", "ai_media_inventory.json")

# Categories whose look a lifestyle cover should keep. Product shots and review
# screenshots would change the page's character, not just its provenance.
_PREFER = ("Shooting_Outdoors_May_2026", "Lifestyle", "Hero-mobile", "Footer")


def _inventory() -> dict:
    try:
        with open(INVENTORY, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _stems(inv: dict, verdict: str) -> dict:
    """{pool key: filename stem} for every image with this verdict."""
    return {k: v["url"].split("?")[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
            for k, v in inv.items()
            if isinstance(v, dict) and v.get("verdict") == verdict and v.get("url")}


def _replacements(inv: dict) -> list[str]:
    """Camera-verified pool keys, closest in character first.

    UNKNOWN images are deliberately excluded. An unclassified image is unclassified
    because Shopify stripped the metadata that would have proven its origin, so
    picking one could silently swap an AI image for another AI image and report
    success. The pool held 47 such images until they were classified by hand on
    2026-08-17; the exclusion stays for whatever is added next.
    """
    photos = [k for k in _stems(inv, "photo") if k in HERO_WHITELIST]
    return sorted(photos, key=lambda k: (not k.startswith(_PREFER), k))


def _list_articles() -> list[dict]:
    out, url = [], (f"{API}/blogs/{BLOG_ID}/articles.json"
                    "?fields=id,title,handle,image&limit=250&published_status=published")
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
    return out


def main() -> None:
    apply = "--apply" in sys.argv
    inv = _inventory()
    ai_stems = _stems(inv, "ai")
    if not ai_stems:
        print("Kein Bild ist als KI eingeordnet — erst scripts/ai_image_scan.py laufen lassen.")
        return
    pool = _replacements(inv)
    if not pool:
        print("⛔ Kein kameraverifiziertes Ersatzbild im Pool. Abbruch — ein UNKNOWN-Bild "
              "als Ersatz würde das Problem nur verschieben.")
        return

    print(f"🖼️  {len(ai_stems)} KI-Bild(er), {len(pool)} geprüfte Ersatzfotos: "
          f"{', '.join(pool[:4])}{' …' if len(pool) > 4 else ''}\n")

    try:
        articles = _list_articles()
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", 0)
        if code in (401, 403):
            print("⛔ Shopify lehnt den Zugriff ab (401/403). Der Token wird zur Laufzeit "
                  "geprägt und ist ~24 h gültig:\n"
                  "     export SHOPIFY_TOKEN=\"$(python3 mint_shopify_token.py)\"\n"
                  "   Schlägt auch das fehl, fehlen SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET "
                  "in der .env.")
        else:
            print(f"⛔ Shopify-API nicht erreichbar: {str(e)[:110]}")
        return
    todo = []
    for a in articles:
        src = ((a.get("image") or {}).get("src") or "")
        hit = next((k for k, stem in ai_stems.items() if stem and stem in src), None)
        if hit:
            todo.append((a, hit))

    if not todo:
        print("✅ Kein veröffentlichter Artikel trägt noch ein KI-Cover.")
        return

    print(f"── {len(todo)} Artikel mit KI-Cover ──")
    ok = fail = 0
    for i, (a, hit) in enumerate(todo):
        new_key = pool[i % len(pool)]
        new_url = HERO_WHITELIST[new_key]
        print(f"\n  {a['handle'][:66]}")
        print(f"     {hit}  →  {new_key}")
        if not apply:
            continue
        try:
            r = requests.put(
                f"{API}/blogs/{BLOG_ID}/articles/{a['id']}.json",
                headers=SHOPIFY_HEADERS, timeout=30,
                json={"article": {"id": a["id"],
                                  # alt text carries the same claim the image makes;
                                  # leaving the old one would describe a photo we
                                  # just removed.
                                  "image": {"src": new_url,
                                            "alt": f"Velluto StradaPro — {a.get('title', '')}"[:120]}}})
            r.raise_for_status()
            ok += 1
            print("     ✓ ersetzt")
        except Exception as e:
            fail += 1
            print(f"     ✗ fehlgeschlagen: {str(e)[:90]}")

    if apply:
        print(f"\n── Ergebnis: {ok} ersetzt, {fail} fehlgeschlagen ──")
        if ok:
            print("   Shopify erzeugt neue CDN-Dateien; die alten bleiben erreichbar, sind "
                  "aber nicht mehr verlinkt. In der GSC neu indexieren lassen.")
    else:
        print(f"\n── Probelauf. Zum Schreiben: "
              f"python3 scripts/replace_ai_covers.py --apply ──")


if __name__ == "__main__":
    main()
