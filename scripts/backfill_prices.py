#!/usr/bin/env python3
"""
One-off: replace every retired 149 price (and the old local-currency prices)
in published articles AND their translations with the new localized
"from 69 EUR" starting price.

Operator decision (Jul 2026): 149 must appear nowhere anymore. Everywhere it
becomes a localized starting price:
  EN from 69 EUR · DE ab 69 EUR · NL vanaf 69 EUR · FR à partir de 69 EUR ·
  ES desde 69 EUR · IT da 69 EUR · PT a partir de 69 EUR ·
  DA fra 515 DKK · NB fra 799 NOK · PL od 299 PLN · SV från 799 SEK

The EN base body uses the "US" (from 69 EUR) wording; each locale translation
gets that locale's wording (from commercial_config.from_price_str_locale).

Matching is currency-anchored so a bare "149" in prose (a year, a stat) is
never touched — only <symbol/word>149 or 149<symbol/word>, plus the old
local prices 1099 DKK / 1499 NOK / 649 PLN / 1599 SEK. A leading price
connector (at/for/just/à/…) is absorbed so prose reads correctly
("at $149" -> "from 69 EUR", not "at from 69 EUR").

Safety: dry-run by default; --apply writes. Full JSON backup of every touched
body + translation to output/price_backups/ before the first write (restore
with --restore <file>). Idempotent. Per-article order: PUT base body ->
re-fetch digests -> re-register each changed translation.

Usage:
  python3 scripts/backfill_prices.py                 # dry-run report
  python3 scripts/backfill_prices.py --apply
  python3 scripts/backfill_prices.py --restore output/price_backups/<f>.json
"""
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from seo_bot import (BLOG_ID, SHOP_LOCALES, SHOPIFY_HEADERS, SHOPIFY_STORE,
                     get_translatable_digests, register_shopify_translation)
from commercial_config import (from_price_str, from_price_str_locale,
                               safe_price_str, amount_str_locale)
from backfill_seo_cleanup import fetch_translations, put_body

APPLY      = "--apply" in sys.argv
ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(ROOT, "output", "price_backups")
REST_DELAY = 0.6

# Old prices to retire. A CURRENCY MARKER is mandatory on at least one side —
# a bare "149" (a year, "149 grams", a stat) is NEVER matched. An optional
# leading price connector (at/for/à/…) is absorbed so prose reads correctly.
_CONNECTOR = r'(?:at|for|just|only|priced\sat|starting\sat|from|à|a|per|voor|vanaf|nur|für|bei|ab|desde|da|od|fra|från|van)\s+'
_EURUSD_149 = re.compile(
    rf'(?:{_CONNECTOR})?'
    r'(?:(?:€|\$|EUR|USD)\s?149(?:\s?(?:€|EUR|euro|USD))?'   # currency BEFORE (+opt after)
    r'|149\s?(?:€|EUR|euro|USD|\$|,-))',                     # currency AFTER only
    re.I)
# Local old prices — currency marker (code or 'kr'/'zł') mandatory.
_LOCAL_OLD = {
    "da": re.compile(rf'(?:{_CONNECTOR})?(?:kr\.?\s?1[.\s]?099|1[.\s]?099\s?(?:DKK|kr\.?))', re.I),
    "nb": re.compile(rf'(?:{_CONNECTOR})?(?:kr\.?\s?1[.\s]?499|1[.\s]?499\s?(?:NOK|kr\.?))', re.I),
    "pl": re.compile(rf'(?:{_CONNECTOR})?649\s?(?:PLN|zł)', re.I),
    "sv": re.compile(rf'(?:{_CONNECTOR})?(?:kr\.?\s?1[.\s]?599|1[.\s]?599\s?(?:SEK|kr\.?))', re.I),
}
# Threshold context ("spending over $149", "meer dan 149 EUR") — the price is a
# market threshold, not a "from" price. Keep the threshold word, drop the "from",
# swap the amount → "over 69 EUR" (grammatical, and 149 still disappears).
# Words cover all shop languages so translations don't get "über ab 69 EUR".
_THRESHOLD_WORDS = (
    r"over|under|above|below|more than|less than|up to"          # en
    r"|über|unter|mehr als|weniger als|bis zu"                   # de
    r"|boven|onder|meer dan|minder dan|tot"                      # nl
    r"|plus de|moins de|au-dessus de|jusqu['’]à|jusqu['’]a"      # fr
    r"|más de|mas de|menos de|hasta"                             # es
    r"|più di|piu di|meno di|oltre|fino a"                       # it
    r"|mais de|acima de|até|ate"                                 # pt
    r"|mere end|mindre end|op til"                               # da
    r"|mer enn|mindre enn|opptil"                                # nb
    r"|powyżej|poniżej|ponad|więcej niż|mniej niż"              # pl
    r"|över|mer än|mindre än|upp till"                           # sv
)
_THRESHOLD = re.compile(
    rf'\b({_THRESHOLD_WORDS})\s+'
    r'(?:(?:€|\$|EUR|USD|kr\.?)\s?(?:149|1[.\s]?099|1[.\s]?499|649|1[.\s]?599)'
    r'(?:\s?(?:€|EUR|euro|USD|DKK|NOK|PLN|SEK|zł|kr\.?))?'
    r'|(?:149|1[.\s]?099|1[.\s]?499|649|1[.\s]?599)\s?(?:€|EUR|euro|USD|\$|DKK|NOK|PLN|SEK|zł|kr\.?))',
    re.I)


def transform(body: str, locale: str | None) -> tuple[str, int]:
    """Replace old prices with the localized from-price. locale=None → EN base
    (US wording). Returns (new_body, n_replacements)."""
    if not body:
        return body, 0
    from_price = from_price_str("US") if locale is None else from_price_str_locale(locale)
    amount = safe_price_str("US") if locale is None else amount_str_locale(locale)
    n = 0
    # threshold context first ("spending over $149" → "spending over 69 EUR")
    body, c = _THRESHOLD.subn(lambda m: f"{m.group(1)} {amount}", body)
    n += c
    # local-currency old price (only for its market)
    if locale in _LOCAL_OLD:
        body, c = _LOCAL_OLD[locale].subn(from_price, body)
        n += c
    # generic EUR/USD 149 everywhere else
    body, c = _EURUSD_149.subn(from_price, body)
    n += c
    return body, n


# ── Shopify sweep ────────────────────────────────────────────────────────────

def list_articles() -> list[dict]:
    out, url = [], (f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
                    "?fields=id,title,handle,body_html&limit=250")
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
        time.sleep(REST_DELAY)
    return out


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def restore(path: str) -> None:
    backup = _load(path, {})
    print(f"Restoring {len(backup.get('articles', []))} articles from {path} …")
    for a in backup["articles"]:
        print(f"  #{a['id']} {a['handle'][:45]}: {'✅' if put_body(a['id'], a['body_html']) else '❌'}")
        digests = get_translatable_digests(a["id"])
        for locale, tr in (a.get("translations") or {}).items():
            if tr.get("body_html"):
                register_shopify_translation(a["id"], locale, tr.get("title", ""),
                                             tr["body_html"], tr.get("meta_description", ""), digests)
    print("Restore done.")


def main() -> None:
    if "--restore" in sys.argv:
        restore(sys.argv[sys.argv.index("--restore") + 1])
        return

    print(f"=== backfill_prices.py [{'APPLY' if APPLY else 'DRY-RUN'}] ===\n")
    articles = list_articles()
    print(f"{len(articles)} articles in blog {BLOG_ID}\n")

    backup = {"created": datetime.datetime.now().isoformat(timespec="seconds"), "articles": []}
    touched = clean = failed = 0

    for a in articles:
        aid, handle, body = a["id"], a.get("handle", ""), a.get("body_html", "") or ""
        new_body, n_base = transform(body, None)

        tr_current, tr_changed = {}, {}
        for locale in SHOP_LOCALES:
            tr = fetch_translations(aid, locale)
            if not tr.get("body_html"):
                continue
            tr_current[locale] = tr
            t_body, t_n = transform(tr["body_html"], locale)
            if t_n:
                tr_changed[locale] = {**tr, "body_html": t_body}

        if not n_base and not tr_changed:
            clean += 1
            continue

        touched += 1
        print(f"[{n_base} in EN + {sum(1 for _ in tr_changed)} locale(s): {sorted(tr_changed)}] "
              f"'{a.get('title','')[:46]}' (#{aid})")
        if not APPLY:
            # show a couple of before/after price snippets for review
            for m in list(_EURUSD_149.finditer(body))[:2]:
                s = max(0, m.start()-25)
                print(f"     …{body[s:m.end()+15].strip()!r} → '{from_price_str('US')}'")
            continue

        backup["articles"].append({"id": aid, "handle": handle,
                                   "body_html": body, "translations": tr_current})
        if n_base and new_body != body and not put_body(aid, new_body):
            failed += 1
            print("     ❌ base body PUT failed — skipping translations")
            continue
        digests = get_translatable_digests(aid)
        for locale, tr in sorted(tr_changed.items()):
            register_shopify_translation(aid, locale, tr.get("title", ""),
                                         tr["body_html"], tr.get("meta_description", ""), digests)
        print("     ✅ updated (EN + translations)")

    if APPLY and backup["articles"]:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(BACKUP_DIR, f"{backup['created'].replace(':', '-')}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False)
        print(f"\n💾 Backup: {path}  (restore with --restore <path>)")

    print(f"\n=== Summary ===\nArticles with old prices: {touched}\nAlready clean: {clean}")
    if APPLY:
        print(f"Failed: {failed}")
    else:
        print("\nDRY-RUN — nothing written. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
