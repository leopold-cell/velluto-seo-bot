#!/usr/bin/env python3
"""
Backfill: strip the injected JS canonical + demote body <h1> on already-
published articles AND their Translate & Adapt locale translations.

Background (GSC + Ahrefs, Jul 2026):
- Every article body carried a client-side JS canonical that stripped the
  locale prefix and pointed all translations at the EN root URL. That
  contradicted Shopify's correct server-side self-canonical + hreflang, so
  Google overrode the declared canonical (GSC: "Duplicate, Google chose a
  different canonical than the user"). seo_bot no longer injects it (see
  build_body_html); this one-off cleans the back-catalogue.
- Older bodies contain an <h1> while the theme renders the article title as
  <h1 class="hero-title"> → two H1s per page (Ahrefs "Multiple H1 tags").
  Body H1s are demoted to <h2>.
- Optional link diagnosis: reports internal links that 3XX/4XX (Ahrefs "Page
  has links to redirect / broken page"); --fix-links rewrites internal
  redirecting hrefs to their final same-host destination.

Safety: dry-run by default; --apply writes. Before the first write, ALL
original bodies + translations are dumped to output/backfill_backups/ (git-
ignored) so every change can be restored. Transforms are anchored regexes
that only touch the exact injected script / <h1> tags. Idempotent.

Per-article order (keeps the translation-outdated window to seconds):
  1. PUT transformed primary body
  2. re-fetch translatable digests (they change with the body)
  3. re-register every locale translation (transformed) against new digests

Usage:
  python3 scripts/backfill_seo_cleanup.py                 # dry-run report
  python3 scripts/backfill_seo_cleanup.py --check-links   # + link diagnosis
  python3 scripts/backfill_seo_cleanup.py --apply         # write
  python3 scripts/backfill_seo_cleanup.py --apply --fix-links
  python3 scripts/backfill_seo_cleanup.py --restore output/backfill_backups/<f>.json
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
                     get_translatable_digests, graphql_with_vars,
                     register_shopify_translation)

APPLY      = "--apply" in sys.argv
CHECK_LNK  = "--check-links" in sys.argv or "--fix-links" in sys.argv
FIX_LINKS  = "--fix-links" in sys.argv
ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(ROOT, "output", "backfill_backups")
SITE       = "https://velluto-shop.com"
REST_DELAY = 0.6  # Shopify REST: 2 req/s

# The exact script build_body_html used to inject (anchored on its unique
# l.rel="canonical" marker; non-greedy to the closing IIFE).
_CANONICAL_JS = re.compile(
    r'<script>\(function\(\)\{var l=document\.createElement\("link"\);'
    r'l\.rel="canonical";.*?\}\)\(\);</script>\s*',
    re.DOTALL,
)
_H1_OPEN  = re.compile(r"<h1\b([^>]*)>", re.I)
_H1_CLOSE = re.compile(r"</h1\s*>", re.I)


# ── pure transforms (unit-testable, no network) ─────────────────────────────

def strip_canonical_js(body: str) -> tuple[str, bool]:
    new = _CANONICAL_JS.sub("", body or "")
    return new, new != (body or "")


def demote_h1(body: str) -> tuple[str, bool]:
    new = _H1_OPEN.sub(r"<h2\1>", body or "")
    new = _H1_CLOSE.sub("</h2>", new)
    return new, new != (body or "")


def transform(body: str) -> tuple[str, list[str]]:
    """Apply all cleanups; returns (new_body, list of change labels)."""
    changes = []
    body, hit = strip_canonical_js(body)
    if hit:
        changes.append("canonical-js")
    body, hit = demote_h1(body)
    if hit:
        changes.append("h1->h2")
    return body, changes


# ── Shopify I/O ──────────────────────────────────────────────────────────────

def list_articles() -> list[dict]:
    out, url = [], (
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        "?fields=id,title,handle,body_html&limit=250"
    )
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=20)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
        time.sleep(REST_DELAY)
    return out


def fetch_translations(article_id: int, locale: str) -> dict:
    """{key: value} of the registered translation for one locale."""
    data = graphql_with_vars(
        """
        query($id: ID!, $locale: String!) {
          translatableResource(resourceId: $id) {
            translations(locale: $locale) { key value }
          }
        }
        """,
        {"id": f"gid://shopify/Article/{article_id}", "locale": locale},
    )
    items = (data.get("translatableResource") or {}).get("translations", [])
    return {t["key"]: t["value"] for t in items if t.get("value")}


def put_body(aid: int, body: str) -> bool:
    r = requests.put(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{aid}.json",
        headers=SHOPIFY_HEADERS,
        json={"article": {"id": aid, "body_html": body}},
        timeout=30,
    )
    time.sleep(REST_DELAY)
    return r.status_code == 200


# ── link diagnosis (Ahrefs: links to redirect / broken page) ────────────────

_HREF = re.compile(r'href="(https?://[^"]+)"')
_URL_CACHE: dict[str, tuple[int, str]] = {}


def check_url(url: str) -> tuple[int, str]:
    """(status, final_url) without following redirects; cached."""
    if url in _URL_CACHE:
        return _URL_CACHE[url]
    try:
        r = requests.head(url, allow_redirects=False, timeout=15,
                          headers={"User-Agent": "Mozilla/5.0 (velluto-backfill)"})
        status, loc = r.status_code, r.headers.get("Location", "")
        if status in (405, 501):  # some hosts reject HEAD
            r = requests.get(url, allow_redirects=False, timeout=15, stream=True,
                             headers={"User-Agent": "Mozilla/5.0 (velluto-backfill)"})
            status, loc = r.status_code, r.headers.get("Location", "")
        if loc.startswith("/"):
            loc = SITE + loc
    except Exception:
        status, loc = -1, ""
    _URL_CACHE[url] = (status, loc)
    return status, loc


def diagnose_links(body: str) -> tuple[str, list[str]]:
    """Report 3XX/4XX links; with --fix-links rewrite INTERNAL redirects whose
    final destination is a same-host 200. External + 4XX are report-only."""
    notes, new_body = [], body
    for url in sorted(set(_HREF.findall(body or ""))):
        status, loc = check_url(url)
        if status in (200, -1):
            continue
        internal = url.startswith(SITE)
        if 300 <= status < 400 and loc:
            # follow one hop for the report / fix target
            final_status, _ = check_url(loc)
            notes.append(f"{'INT' if internal else 'EXT'} {status} {url} -> {loc} ({final_status})")
            if FIX_LINKS and internal and loc.startswith(SITE) and final_status == 200:
                new_body = new_body.replace(f'href="{url}"', f'href="{loc}"')
        elif status >= 400:
            notes.append(f"{'INT' if internal else 'EXT'} {status} {url} (BROKEN — fix manually)")
    return new_body, notes


# ── restore mode ─────────────────────────────────────────────────────────────

def restore(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        backup = json.load(f)
    print(f"Restoring {len(backup['articles'])} articles from {path} …")
    for a in backup["articles"]:
        ok = put_body(a["id"], a["body_html"])
        print(f"  #{a['id']} {a['handle'][:45]}: {'✅' if ok else '❌'}")
        digests = get_translatable_digests(a["id"])
        for locale, tr in (a.get("translations") or {}).items():
            if tr.get("body_html"):
                register_shopify_translation(
                    a["id"], locale, tr.get("title", ""), tr["body_html"],
                    tr.get("meta_description", ""), digests)
    print("Restore done.")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if "--restore" in sys.argv:
        restore(sys.argv[sys.argv.index("--restore") + 1])
        return

    mode = "APPLY" if APPLY else "DRY-RUN"
    print(f"=== backfill_seo_cleanup.py [{mode}]"
          f"{' +links' if CHECK_LNK else ''}{' +fix-links' if FIX_LINKS else ''} ===\n")
    articles = list_articles()
    print(f"{len(articles)} articles in blog {BLOG_ID}\n")

    backup = {"created": datetime.datetime.now().isoformat(timespec="seconds"),
              "articles": []}
    touched = clean = failed = 0
    all_link_notes: list[str] = []

    for a in articles:
        aid, handle, body = a["id"], a.get("handle", ""), a.get("body_html", "") or ""
        new_body, changes = transform(body)
        link_notes: list[str] = []
        if CHECK_LNK:
            new_body, link_notes = diagnose_links(new_body)
            if FIX_LINKS and link_notes and new_body != body and "links" not in changes:
                changes.append("links")
            all_link_notes += [f"  #{aid} {n}" for n in link_notes]

        # translations: fetch current values, transform them the same way
        # (always checked — a translation can carry the canonical/H1 even if
        # the primary body was already cleaned, and vice versa)
        tr_current: dict[str, dict] = {}
        tr_changed: dict[str, dict] = {}
        for locale in SHOP_LOCALES:
            tr = fetch_translations(aid, locale)
            if not tr:
                continue
            tr_current[locale] = tr
            t_body, t_changes = transform(tr.get("body_html", ""))
            if t_changes:
                tr_changed[locale] = {**tr, "body_html": t_body}

        if not changes and not tr_changed:
            clean += 1
            continue

        touched += 1
        print(f"[{','.join(changes) or 'translations-only'}] '{a.get('title','')[:48]}' "
              f"(#{aid}) — locales to fix: {sorted(tr_changed) or '—'}")
        for n in link_notes:
            print(f"     link: {n}")

        if not APPLY:
            continue

        # backup BEFORE writing
        backup["articles"].append({"id": aid, "handle": handle,
                                   "body_html": body, "translations": tr_current})

        ok = put_body(aid, new_body) if (changes and new_body != body) else True
        if not ok:
            failed += 1
            print("     ❌ body PUT failed — skipping translation re-register")
            continue
        digests = get_translatable_digests(aid)
        for locale, tr in sorted(tr_changed.items()):
            register_shopify_translation(
                aid, locale, tr.get("title", ""), tr["body_html"],
                tr.get("meta_description", ""), digests)
        print("     ✅ updated")

    if APPLY and backup["articles"]:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(
            BACKUP_DIR, f"{backup['created'].replace(':', '-')}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False)
        print(f"\n💾 Backup written: {path}  (restore with --restore <path>)")

    print("\n=== Summary ===")
    print(f"Articles needing cleanup: {touched}")
    print(f"Already clean:            {clean}")
    if APPLY:
        print(f"Failed:                   {failed}")
    if all_link_notes:
        print(f"\nLink issues ({len(all_link_notes)}):")
        print("\n".join(all_link_notes))
    if not APPLY:
        print("\nDRY-RUN — no changes written. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
