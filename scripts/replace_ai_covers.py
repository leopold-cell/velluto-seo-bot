#!/usr/bin/env python3
"""
Replace AI-generated cover images on published articles with real photographs.

WHY
Six images in the cover pool are OpenAI gpt-image 2.0 output, not photographs —
see data/ai_media_inventory.json and the Phase 4.6 note in seo_bot.py. They were
removed from the pool on 2026-08-17, which stops NEW articles from drawing them.
It does nothing for the articles already published with one, and those are the
ones the public sees.

Nine articles carry such a cover. Each file still ships its C2PA manifest from
our own CDN, so the AI origin is verifiable by anyone at
contentcredentials.org/verify — Art. 50(4) AI Act (image content that appears
authentic) and § 5a UWG (a photorealistic AI image suggesting a real riding
situation). Swapping the image settles both without a disclosure label.

WHAT IT PICKS
A camera-verified photo from the same visual category, so the page keeps its
look. Only images the scan classified "photo" are eligible: an UNKNOWN image
would just move the problem, since Shopify strips the metadata that would have
proven its origin. Assignment is round-robin so nine articles do not all end up
with the same cover.

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

from seo_bot import BLOG_ID, SHOPIFY_HEADERS, SHOPIFY_STORE, WHITELIST  # noqa: E402

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

    UNKNOWN images are deliberately excluded. 47 of them are unclassified only
    because Shopify stripped their metadata, so picking one could silently swap
    an AI image for another AI image and report success.
    """
    photos = [k for k in _stems(inv, "photo") if k in WHITELIST]
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

    articles = _list_articles()
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
        new_url = WHITELIST[new_key]
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
