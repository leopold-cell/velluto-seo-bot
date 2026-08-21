#!/usr/bin/env python3
"""
Put a product module into the top-traffic articles — the blog→shop door.

WHY
The August numbers: non-brand search brings ~467 clicks/month and ~3 orders —
0.64% conversion, while brand traffic converts at ~2.5%. The blog reader has
buying intent (they searched "best cycling glasses 2026") but the article path
to the product is thin: body links exist since the money-page auto-fix, yet
nothing in the article *shows* the product. At 0.64% every traffic win is nearly
worthless — +230 clicks from fixing cannibalisation would yield 1.5 orders. At
2% the same clicks yield 4.6. Conversion multiplies every other lever, which is
why this module, not more traffic, is the first move.

WHAT IT INJECTS
One compact card after the first content section (before the second <h2>):
product image, the evidenced specs the pipeline is allowed to claim (25 g,
UV400-certified, tool-free lens change, anti-fog, 30-day trial, from 69 EUR)
and a link to the canonical money page. No superlatives, no competitor names —
the card must pass check_compliance like everything else.

Idempotent via an HTML marker; re-running never duplicates the card. Removing a
card by hand stays removed unless --apply runs again by intent.

TARGETS
By default: blog pages in gsc_data.json (GSC top_pages) with >= MIN_IMPR
impressions — the pages where readers actually are. Override with --handles.

Usage:
  python3 scripts/product_module.py                 # dry-run: show plan
  python3 scripts/product_module.py --apply
  python3 scripts/product_module.py --handles a,b --apply
  python3 scripts/product_module.py --print-html    # emit the card HTML only
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MARKER = "velluto-product-module-v1"
MIN_IMPR = 250
SHOP = "https://velluto-shop.com"
MONEY_PAGE = f"{SHOP}/collections/velluto-stradapro-cycling-glasses"
IMG = ("https://cdn.shopify.com/s/files/1/0621/5607/9275/files/"
       "Velluto_Starter_Vision_Kit_Nero.webp?v=1783512072&width=360")


def build_html() -> str:
    """The card. Inline styles only — article bodies carry no stylesheet.
    Every claim in here is an evidenced spec the legal gate already allows."""
    return f"""
<!-- {MARKER} -->
<aside style="margin:2em 0;padding:1.1em 1.25em;border:1px solid #e3e3e3;border-radius:12px;display:flex;gap:1.1em;align-items:center;flex-wrap:wrap;background:#fafafa">
  <a href="{MONEY_PAGE}" style="flex:0 0 108px"><img src="{IMG}" alt="Velluto StradaPro cycling glasses" width="108" height="108" loading="lazy" style="max-width:100%;height:auto;border-radius:8px"></a>
  <div style="flex:1 1 240px;min-width:220px">
    <p style="margin:0 0 .25em;font-weight:600">Velluto StradaPro</p>
    <p style="margin:0 0 .6em;font-size:.92em;color:#444">25 g &middot; UV400-certified &middot; tool-free lens change &middot; anti-fog coating</p>
    <a href="{MONEY_PAGE}" style="display:inline-block;padding:.55em 1.1em;background:#111;color:#fff;border-radius:8px;text-decoration:none;font-size:.95em">Try it 30 days &mdash; from 69&nbsp;EUR</a>
  </div>
</aside>
""".strip() + "\n"


def inject(body: str) -> tuple[str, str]:
    """(new_body, where). After the first content section: before the second
    <h2>. Articles with fewer than two h2 sections get it appended before the
    FAQ block, or at the end — late is worse than early, but a malformed insert
    in the middle of a table would be worse than either."""
    if MARKER in body:
        return body, "skip (already present)"
    card = build_html()
    h2s = [m.start() for m in re.finditer(r"<h2[^>]*>", body, re.I)]
    if len(h2s) >= 2:
        i = h2s[1]
        return body[:i] + card + body[i:], "before 2nd h2"
    m = re.search(r'<h2[^>]*id=["\']sfaq|<details', body, re.I)
    if m:
        return body[:m.start()] + card + body[m.start():], "before FAQ"
    return body + "\n" + card, "appended"


def targets() -> list[str]:
    if "--handles" in sys.argv:
        i = sys.argv.index("--handles")
        return [h.strip() for h in sys.argv[i + 1].split(",") if h.strip()]
    try:
        with open(os.path.join(ROOT, "gsc_data.json"), encoding="utf-8") as f:
            pages = (json.load(f) or {}).get("top_pages") or []
    except Exception:
        return []
    out = []
    for p in sorted(pages, key=lambda x: -x.get("impressions", 0)):
        url = (p.get("keys") or [""])[0]
        if "/blogs/" in url and p.get("impressions", 0) >= MIN_IMPR:
            out.append(url.rstrip("/").rsplit("/", 1)[-1])
    return out


def main() -> None:
    if "--print-html" in sys.argv:
        print(build_html())
        return

    apply = "--apply" in sys.argv
    handles = targets()
    if not handles:
        print("Keine Zielartikel — gsc_data.json fehlt oder kein Blog-Eintrag "
              f">= {MIN_IMPR} Impressionen. --handles a,b geht immer.")
        return

    # The card itself must clear the same legal gate as any published text.
    try:
        from briefs.quality_gate import check_compliance
        issues = check_compliance({"title": "", "body_html": build_html()})
        if issues:
            print("⛔ Modul-HTML fällt durchs Legal-Gate — nichts geschrieben:")
            for x in issues:
                print(f"   {x}")
            return
    except ImportError:
        print("   ⚠️  quality_gate nicht importierbar — Gate-Prüfung übersprungen")

    import time

    import requests
    from seo_bot import BLOG_ID, SHOPIFY_HEADERS, SHOPIFY_STORE
    api = f"https://{SHOPIFY_STORE}/admin/api/2024-01"

    def _resolve(h: str) -> str:
        """GSC still lists pre-rename URLs: tested-ranked-compared 301s to
        best-cycling-glasses-2026 since the legal slug fix. Looking the old
        handle up in the Admin API finds nothing, so follow the public redirect
        to today's handle. Throttled — bursting these earned 429s three times
        in this repo's history already."""
        try:
            time.sleep(1.2)
            r = requests.head(f"{SHOP}/blogs/velluto-the-magazine/{h}",
                              allow_redirects=True, timeout=20,
                              headers={"User-Agent": "Velluto-product-module/1.0"})
            final = r.url.rstrip("/").rsplit("/", 1)[-1]
            return final if r.status_code == 200 else h
        except Exception:
            return h

    print(f"=== product_module [{'APPLY' if apply else 'DRY-RUN'}] — "
          f"{len(handles)} Artikel ===\n")
    ok = 0
    seen: set[str] = set()
    for h in handles:
        try:
            r = requests.get(f"{api}/blogs/{BLOG_ID}/articles.json",
                             params={"handle": h, "fields": "id,handle,body_html"},
                             headers=SHOPIFY_HEADERS, timeout=30)
            r.raise_for_status()
            arts = r.json().get("articles", [])
            if not arts:
                h2 = _resolve(h)
                if h2 != h:
                    print(f"  ↪ {h} → {h2} (301 aufgelöst)")
                    r = requests.get(f"{api}/blogs/{BLOG_ID}/articles.json",
                                     params={"handle": h2, "fields": "id,handle,body_html"},
                                     headers=SHOPIFY_HEADERS, timeout=30)
                    r.raise_for_status()
                    arts = r.json().get("articles", [])
                    h = h2
        except Exception as e:
            print(f"  ✗ {h}: {str(e)[:80]}")
            continue
        if not arts:
            print(f"  ✗ {h}: nicht gefunden")
            continue
        if h in seen:      # two stale GSC URLs can resolve to the same article
            print(f"  · {h}: schon behandelt (Duplikat nach Redirect)")
            continue
        seen.add(h)
        a = arts[0]
        new_body, where = inject(a.get("body_html") or "")
        print(f"  {'·' if where.startswith('skip') else '✓'} {h}: {where}")
        if where.startswith("skip") or not apply:
            continue
        try:
            r = requests.put(f"{api}/blogs/{BLOG_ID}/articles/{a['id']}.json",
                             headers=SHOPIFY_HEADERS, timeout=30,
                             json={"article": {"id": a["id"], "body_html": new_body}})
            r.raise_for_status()
            ok += 1
        except Exception as e:
            print(f"     ✗ Schreiben fehlgeschlagen: {str(e)[:80]}")
    if apply:
        print(f"\n{ok} Artikel aktualisiert.")
    else:
        print("\nDRY-RUN — nichts geschrieben. Mit --apply anwenden.")


if __name__ == "__main__":
    main()
