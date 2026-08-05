#!/usr/bin/env python3
"""
Make comparison-table Yes/No cells symmetric across all columns.

Observed live: the same answer carried opposite spin depending on whose column
it sat in.

    Interchangeable Lenses | Yes, brand-specific | Yes, Oakley only | Yes, tool-free click-in

Every cell says "Yes". The rival's qualifier narrows it, Velluto's widens it.
That is asymmetric framing under § 6 UWG (the L3c/L6 rules in the generation
prompt) and reads as subtly disparaging even where each single word is true.

This strips the qualifier from EVERY column, Velluto's included — symmetry, not
censorship. The detail belongs in the prose, where it can be attributed; a
one-word table cell cannot carry it fairly.

WHAT THIS DOES NOT FIX
  Prose cells ("Passive ventilation" vs "Built-in anti-fog system") are equally
  asymmetric but cannot be normalised mechanically — a regex cannot know whether
  Oakley ships a coating, and guessing would invent a fact. New articles are
  covered by the strengthened L6 rule in the prompt; existing ones would need an
  LLM pass. Run with --report-prose to list the affected rows.

Mechanical only: no LLM, no cost. EN bodies only — locale translations keep
their tables until re-adapted. Idempotent. Dry-run by default.

Usage:
  python3 scripts/normalize_tables.py                  # dry-run
  python3 scripts/normalize_tables.py --apply          # write
  python3 scripts/normalize_tables.py --report-prose   # list asymmetric prose rows
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from briefs.quality_gate import normalize_comparison_cells
from seo_bot import SHOPIFY_STORE, SHOPIFY_HEADERS, BLOG_ID

APPLY = "--apply" in sys.argv
PROSE = "--report-prose" in sys.argv

# Words that only ever show up on Velluto's side of a row — the tell that a prose
# cell was written to flatter rather than to describe.
_ENRICHERS = re.compile(
    r"\b(built-?in|integrated|tool-?free|risk-?free|advanced|premium|proprietary|"
    r"dedicated|full|complete|enhanced|superior|genuine)\b", re.I)


def _list_articles() -> list[dict]:
    out, url = [], (
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        "?fields=id,title,handle,body_html&limit=250&published_status=published"
    )
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
    return out


def _rows(html: str):
    for tm in re.finditer(r"<table\b.*?</table>", html or "", re.S | re.I):
        for rm in re.finditer(r"<tr\b.*?</tr>", tm.group(0), re.S | re.I):
            cells = [re.sub(r"<[^>]+>", "", c).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rm.group(0), re.S | re.I)]
            if len(cells) >= 3:
                yield cells


def _asymmetric_prose(cells: list[str]) -> bool:
    """Last column enriched, the others not — and none of them a bare Yes/No."""
    metric, values = cells[0], cells[1:]
    if any(re.match(r"^\s*(yes|no)\b", v, re.I) for v in values):
        return False           # Yes/No rows are handled mechanically
    if len(values) < 2:
        return False
    ours, theirs = values[-1], values[:-1]
    return bool(_ENRICHERS.search(ours)) and not any(_ENRICHERS.search(t) for t in theirs)


def main() -> None:
    print(f"=== normalize_tables.py [{'APPLY' if APPLY else 'DRY-RUN'}] ===\n")
    articles = _list_articles()
    with_tables = [a for a in articles if "<table" in (a.get("body_html") or "").lower()]
    print(f"{len(articles)} published · {len(with_tables)} with a comparison table\n")

    if PROSE:
        n = 0
        for a in with_tables:
            hits = [c for c in _rows(a["body_html"] or "") if _asymmetric_prose(c)]
            if not hits:
                continue
            n += 1
            print(f"• {a.get('handle','')[:58]}")
            for c in hits[:4]:
                print(f"    {c[0][:26]:<26} | " + " | ".join(x[:24] for x in c[1:]))
        print(f"\n{n} article(s) with asymmetric PROSE rows — these need an LLM pass, "
              f"not a regex. New articles are covered by the L6 prompt rule.")
        return

    total_cells = changed_articles = 0
    for a in with_tables:
        new_body, n = normalize_comparison_cells(a["body_html"] or "")
        if not n:
            continue
        changed_articles += 1
        total_cells += n
        print(f"• {a.get('handle','')[:58]} — {n} cell(s)")
        for c in _rows(a["body_html"] or ""):
            if any(re.match(r"^\s*(?:Yes|No)\b\s*[,;:–—-]\s*\S", x, re.I) for x in c[1:]):
                print(f"    {c[0][:26]:<26} | " + " | ".join(x[:24] for x in c[1:]))
        if APPLY:
            r = requests.put(
                f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{a['id']}.json",
                headers=SHOPIFY_HEADERS, timeout=20,
                json={"article": {"id": a["id"], "body_html": new_body}})
            print(f"    {'✅ written' if r.status_code == 200 else '❌ failed ' + str(r.status_code)}")

    print(f"\n=== {total_cells} cell(s) in {changed_articles} article(s) ===")
    if not APPLY and total_cells:
        print("DRY-RUN — nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main()
