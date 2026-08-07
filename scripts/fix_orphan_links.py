#!/usr/bin/env python3
"""
Give orphaned articles inbound internal links again.

WHY THIS EXISTS
scripts/scrub_drafted_links.py correctly strips internal links to articles that
have gone offline — a link to a 404 wastes crawl budget and leaks link equity.
But the removal is one-way: when the article is later repaired and republished
(scripts/legal_retrofit.py --rewrite --drafted-only), the links do NOT come back.
After the 2026-08-05 repair run, 5 of the 16 restored articles had zero inbound
links and were reachable only through the sitemap.

That matters more than a one-off "request indexing" click. Google has no public
API for that (URL Inspection is manual, the Indexing API covers only JobPosting
and BroadcastEvent, and this repo's OAuth scope is webmasters.readonly anyway).
Internal linking is the strongest crawl signal we can actually control, and it
keeps working instead of firing once.

WHAT IT DOES
  1. Reads every published article and builds the inbound-link map.
  2. Orphans = zero inbound links from OTHER articles (a page's own canonical /
     og:url reference to itself does not count).
  3. For each orphan, scores live articles by distinctive-token overlap with the
     orphan's title and picks the best few as link sources.
  4. Appends the link to the source's existing "Related reading" aside, or adds
     one — the same markup ensure_related_links() writes at publish time.

Conservative on purpose: at most --max-sources links per orphan, never a source
that already links there, never a self-link. Mechanical, no LLM, no cost.
Idempotent. Dry-run by default.

Usage:
  python3 scripts/fix_orphan_links.py                    # dry-run
  python3 scripts/fix_orphan_links.py --apply
  python3 scripts/fix_orphan_links.py --max-sources 3 --apply
  python3 scripts/fix_orphan_links.py --handles a-handle,b-handle --apply
"""
import html as html_mod
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from briefs.quality_gate import _rel_tokens
from seo_bot import SHOPIFY_STORE, SHOPIFY_HEADERS, BLOG_ID

APPLY = "--apply" in sys.argv
MAX_SOURCES = 2
if "--max-sources" in sys.argv:
    i = sys.argv.index("--max-sources")
    if i + 1 < len(sys.argv):
        MAX_SOURCES = max(1, int(sys.argv[i + 1]))

# A single shared title word is not a topic match. Live data showed exactly why:
# "worth", "specs", "complete" — and "amp", harvested from a &amp; entity — paired
# unrelated articles. Two shared words is where the pairs become real
# (anti+fog, oakley+alternatives, expensive+worth).
MIN_OVERLAP = 2

# Scope: default is every orphan; --handles limits it to a known set, which is what
# a targeted repair after a republish run wants.
ONLY: set[str] = set()
if "--handles" in sys.argv:
    i = sys.argv.index("--handles")
    if i + 1 < len(sys.argv):
        ONLY = {h.strip() for h in sys.argv[i + 1].split(",") if h.strip()}

BLOG_HANDLE = "velluto-the-magazine"
SITE = "https://velluto-shop.com"

# Topic clusters, matched against the handle.
#
# Token overlap alone reaches only ~23% of the orphans, and the reason is
# structural, not a tuning problem: _REL_STOPWORDS strips the entire domain
# vocabulary (cycling, glasses, road, lens, best, guide, 2026), so most titles
# keep just one distinguishing word and "share >= 2" almost never fires. Two
# anti-fog articles are obviously related; the tokeniser cannot see it.
#
# This map encodes the topic structure the titles already follow. Measured on the
# live corpus: 58 of 71 articles land in a cluster (82%). The 13 that do not are
# the broad buying guides — they are the general entry points, not orphans of a
# missing topic, so they are deliberately left uncategorised.
TOPIC_CLUSTERS = {
    "oakley-alternatives": r"oakley|sungod|roka|poc|sigma|kapvoe|evileye|endurasport"
                           r"|alibaba|smith|decathlon|girly|bing|premium-brands",
    "anti-fog":            r"anti-?fog|fog|ventilation",
    "lens-system":         r"interchangeable|lens-replacement|lenses|photochromic|polaris",
    "fit":                 r"narrow|small-face|big-head|fit|womens|gender",
    "price-value":         r"expensive|worth|budget|value|under-150|how-much|cost",
    "conditions":          r"weather|winter|summer|cold|wet|gravel|tour-de-france"
                           r"|amstel|long-rides",
    "uv-tech":             r"uv400|uv-protection|uv380|lightweight|gram|aero"
                           r"|half-vs-full|smart|ar-glasses",
}


def _topic_of(handle: str) -> str:
    """First matching cluster — order matters, brand beats generic."""
    for name, pat in TOPIC_CLUSTERS.items():
        if re.search(pat, handle or "", re.I):
            return name
    return ""


def _list_articles() -> list[dict]:
    out, url = [], (
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        "?fields=id,title,handle,body_html,tags,created_at&limit=250"
        "&published_status=published"
    )
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
    return out


def _links_to(body: str, handle: str) -> bool:
    """A real <a href> to that article — NOT a bare mention of the handle.

    Matching the handle anywhere in the HTML would count the page's own canonical
    and og:url, which is how an earlier count made 40 orphans look like 5.
    """
    return bool(re.search(r'href="[^"]*/blogs/[^"/]+/' + re.escape(handle) + r'(?:[?#][^"]*)?"',
                          body or "", re.I))


def _clean_title(t: str) -> str:
    """Un-escape entities before tokenising — otherwise '&amp;' contributes the
    token 'amp', which then 'matches' every other title containing an ampersand."""
    return html_mod.unescape(t or "").split("|")[0].strip()


def _inject(body: str, title: str, url: str) -> str:
    """Append to the existing Related-reading aside, or create one — mirroring
    ensure_related_links() so both paths produce the same markup."""
    item = f'<li><a href="{url}">{title}</a></li>'
    aside = re.search(r'(<aside class="vmag-related-inline">.*?<ul>)(.*?)(</ul>\s*</aside>)',
                      body, re.S | re.I)
    if aside:
        return body[:aside.end(2)] + item + body[aside.end(2):]
    block = ('<aside class="vmag-related-inline"><p><strong>Related reading:</strong></p>'
             f'<ul>{item}</ul></aside>')
    if re.search(r'<h2[^>]*id=["\']sfaq', body, re.I):
        return re.sub(r'(<h2[^>]*id=["\']sfaq)', block + r"\1", body, count=1, flags=re.I)
    if re.search(r'<details', body, re.I):
        return re.sub(r'(<details)', block + r"\1", body, count=1, flags=re.I)
    return body + "\n" + block


def main() -> None:
    print(f"=== fix_orphan_links.py [{'APPLY' if APPLY else 'DRY-RUN'}] "
          f"max {MAX_SOURCES} source(s)/orphan ===\n")
    arts = _list_articles()
    print(f"{len(arts)} published articles\n")

    inbound = {a["handle"]: 0 for a in arts if a.get("handle")}
    for a in arts:
        for h in inbound:
            if h != a.get("handle") and _links_to(a.get("body_html", ""), h):
                inbound[h] += 1

    orphans = [a for a in arts if a.get("handle") and inbound.get(a["handle"], 0) == 0]
    all_orphans = len(orphans)
    if ONLY:
        orphans = [o for o in orphans if o["handle"] in ONLY]
        missing = ONLY - {o["handle"] for o in orphans}
        if missing:
            print(f"   ⓘ already linked or unknown, skipped: {sorted(missing)}\n")
    print(f"{all_orphans} orphan(s) site-wide — no inbound internal link"
          + (f"; {len(orphans)} in scope" if ONLY else "") + ":\n")
    for o in orphans:
        print(f"  • {o['handle']}")
    if not orphans:
        return

    # Edits accumulate per source article, so two orphans can share one source
    # without the second write discarding the first.
    pending: dict[int, str] = {}
    plan: list[tuple[str, str, str]] = []

    # Pairwise overlap once — reused for source ranking and for the clusters.
    toks = {a["handle"]: _rel_tokens(_clean_title(a.get("title", "")), a.get("tags", ""))
            for a in arts}
    overlap: dict[str, dict[str, int]] = {a["handle"]: {} for a in arts}
    for i, a in enumerate(arts):
        for b in arts[i + 1:]:
            n = len(toks[a["handle"]] & toks[b["handle"]])
            if n:
                overlap[a["handle"]][b["handle"]] = n
                overlap[b["handle"]][a["handle"]] = n
    by_handle = {a["handle"]: a for a in arts}
    orphan_handles = {x["handle"] for x in orphans}
    weak = 0

    for o in orphans:
        url = f"{SITE}/blogs/{BLOG_HANDLE}/{o['handle']}"
        oh = o["handle"]

        def _candidates(min_n: int):
            out = []
            for cand, n in overlap.get(oh, {}).items():
                if n < min_n or cand in orphan_handles:
                    continue          # never hang an orphan off another orphan
                a = by_handle[cand]
                if _links_to(pending.get(a["id"], a.get("body_html", "")), oh):
                    continue
                out.append((n, a.get("created_at", ""), a))
            # Sort on the first two fields only — the third is a dict, and on a tie
            # Python would fall through to comparing dicts and raise TypeError.
            out.sort(key=lambda x: (x[0], x[1] or ""), reverse=True)
            return out

        # Primary signal: the curated topic cluster. Ranked inside the cluster by
        # token overlap, so the closest sibling wins; recency breaks ties.
        topic = _topic_of(oh)
        scored, tier = [], ""
        if topic:
            for cand, a in by_handle.items():
                if cand == oh or cand in orphan_handles or _topic_of(cand) != topic:
                    continue
                if _links_to(pending.get(a["id"], a.get("body_html", "")), oh):
                    continue
                scored.append((overlap.get(oh, {}).get(cand, 0),
                               a.get("created_at", ""), a))
            scored.sort(key=lambda x: (x[0], x[1] or ""), reverse=True)
            tier = f"  [{topic}]"
        if not scored:
            # No cluster (the broad buying guides) — fall back to raw token overlap.
            scored = _candidates(MIN_OVERLAP)
            tier = "  [token match]"
            if scored:
                weak += 1
        if not scored:
            print(f"\n  ⚠️  {oh[:50]}: no source in its topic cluster — needs a hub page or a rewrite")
            continue
        print(f"\n  → {oh[:52]}{tier}")
        for n, _, src in scored[:MAX_SOURCES]:
            body = pending.get(src["id"], src.get("body_html", ""))
            pending[src["id"]] = _inject(body, o.get("title", ""), url)
            plan.append((src["handle"], oh, f"{n} shared token(s)"))
            print(f"       from {src['handle'][:48]}  ({n} shared token(s))")

    print(f"\n=== {len(plan)} link(s) across {len(pending)} source article(s)"
          + (f"; {weak} via cluster fallback" if weak else "") + " ===")
    if not APPLY:
        print("DRY-RUN — nothing written. Re-run with --apply.")
        return

    ok = 0
    for aid, body in pending.items():
        r = requests.put(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{aid}.json",
            headers=SHOPIFY_HEADERS, timeout=20,
            json={"article": {"id": aid, "body_html": body}})
        ok += int(r.status_code == 200)
        if r.status_code != 200:
            print(f"   ❌ article {aid}: HTTP {r.status_code}")
    print(f"✓ {ok}/{len(pending)} source article(s) updated.")


if __name__ == "__main__":
    main()
