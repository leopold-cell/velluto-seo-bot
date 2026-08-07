#!/usr/bin/env python3
"""
Rename URL slugs that carry a legal claim, with a 301 for the old address.

WHY THE SLUGS SURVIVED EVERY EARLIER FIX
scripts/legal_retrofit.py cleans the title and the body, then calls
seo_bot.replace_article(), which deliberately keeps the handle so the URL and its
rankings survive (seo_bot.py, "same handle/URL"). Correct for SEO, wrong here:
the claim moved out of the headline and stayed in the address, where Google
prints it under every result. scripts/legal_watchdog.py found 9 of these.

HOW THE NEW SLUG IS DERIVED
From the article's CURRENT title, not by deleting words from the old slug. The
titles were already cleaned (TITLE_OVERRIDES + legal_heal), so slugifying one
yields a slug that is both compliant and an honest description of the page. The
result is re-checked against check_compliance before anything is written — a
derived slug is not assumed to be clean just because its source was.

REDIRECTS ARE EXPLICIT
Shopify's automatic redirect on handle change is not something to rely on for a
legal fix, so this creates the 301 itself via the Redirect API and verifies it.
Without it every inbound link, every Google result and the GSC history for the
old URL would 404 — the exact damage the last repair run was undoing.

Idempotent (an already-clean slug is skipped). Dry-run by default.

Usage:
  python3 scripts/fix_slugs.py            # dry-run: show old → new
  python3 scripts/fix_slugs.py --apply
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from briefs.quality_gate import check_compliance
from seo_bot import SHOPIFY_STORE, SHOPIFY_HEADERS, BLOG_ID

APPLY = "--apply" in sys.argv
BLOG_HANDLE = "velluto-the-magazine"
API = f"https://{SHOPIFY_STORE}/admin/api/2024-01"


def _slug_text(handle: str) -> str:
    """Handle → words, so check_compliance can read it the way a reader does."""
    return (handle or "").replace("-", " ")


def _slugify(title: str) -> str:
    s = (title or "").lower()
    s = s.replace("&", " and ").replace("|", " ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)[:100].strip("-")


def _list_articles() -> list[dict]:
    out, url = [], (f"{API}/blogs/{BLOG_ID}/articles.json"
                    "?fields=id,title,handle&limit=250&published_status=published")
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
    return out


def _create_redirect(old: str, new: str) -> bool:
    path = f"/blogs/{BLOG_HANDLE}/{old}"
    target = f"/blogs/{BLOG_HANDLE}/{new}"
    try:
        r = requests.post(f"{API}/redirects.json", headers=SHOPIFY_HEADERS, timeout=20,
                          json={"redirect": {"path": path, "target": target}})
        if r.status_code in (200, 201):
            return True
        # 422 = already exists, which is success for our purposes.
        if r.status_code == 422 and "already" in r.text.lower():
            return True
        print(f"      redirect failed {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"      redirect error: {e}")
    return False


def main() -> None:
    print(f"=== fix_slugs.py [{'APPLY' if APPLY else 'DRY-RUN'}] ===\n")
    arts = _list_articles()
    taken = {a["handle"] for a in arts}

    todo = []
    for a in arts:
        old = a.get("handle") or ""
        if not old or not check_compliance({"title": "", "body_html": _slug_text(old)}):
            continue
        new = _slugify(a.get("title", ""))
        if not new or new == old:
            print(f"  ⚠️  {old[:58]}\n      title yields no usable slug — fix the title first")
            continue
        if check_compliance({"title": "", "body_html": _slug_text(new)}):
            print(f"  ⚠️  {old[:58]}\n      derived slug still trips the gate: {new}")
            continue
        base, n = new, 2
        while new in taken:                     # never collide with a live article
            new = f"{base}-{n}"
            n += 1
        taken.add(new)
        todo.append((a, old, new))

    print(f"{len(arts)} published · {len(todo)} slug(s) to rename\n")
    for _, old, new in todo:
        print(f"  {old}\n    → {new}\n")
    if not todo:
        return
    if not APPLY:
        print("DRY-RUN — nothing written. Re-run with --apply.")
        return

    done = 0
    for a, old, new in todo:
        r = requests.put(f"{API}/blogs/{BLOG_ID}/articles/{a['id']}.json",
                         headers=SHOPIFY_HEADERS, timeout=20,
                         json={"article": {"id": a["id"], "handle": new}})
        if r.status_code not in (200, 201):
            print(f"  ❌ {old}: rename failed {r.status_code}")
            continue
        # Redirect FIRST-class: a renamed article without one is a fresh 404.
        ok = _create_redirect(old, new)
        done += 1
        print(f"  ✅ {new}" + ("" if ok else "   ⚠️ REDIRECT MISSING — add manually!"))
    print(f"\n✓ {done}/{len(todo)} renamed. Re-submit the new URLs in GSC; the 301 "
          f"carries the old rankings across.")


if __name__ == "__main__":
    main()
