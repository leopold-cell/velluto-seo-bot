#!/usr/bin/env python3
"""
Flatten redirect chains — every 301 should point at its FINAL destination.

WHY
Renames and merges compose over time: fix_slugs sent
best-cycling-glasses-2026-tested-ranked-compared → best-cycling-glasses-2026,
then merge_duplicates (2026-08-21) sent best-cycling-glasses-2026 onward to
best-cycling-glasses-2026-the-complete-buying-guide. The old redirect now takes
two hops. Google follows short chains, but each hop costs crawl budget and
dilutes the signal — and chains only ever grow as more renames land on top.

WHAT IT DOES
Reads all URL redirects, resolves each target through the path→target map until
it stops moving (cycle-guarded), and updates every redirect whose final
destination differs from its stored target. Mechanical, no LLM, idempotent:
once flat, there is nothing to do. Safe as a daily pipeline step — it only ever
rewrites redirect targets, never paths, pages or articles.

Usage:
  python3 scripts/flatten_redirect_chains.py            # dry-run
  python3 scripts/flatten_redirect_chains.py --apply
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from seo_bot import SHOPIFY_HEADERS, SHOPIFY_STORE

API = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
APPLY = "--apply" in sys.argv


def fetch_redirects() -> list[dict]:
    out, url = [], f"{API}/redirects.json?limit=250"
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        out.extend(r.json().get("redirects", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
    return out


def resolve(target: str, by_path: dict[str, str]) -> str:
    """Follow the chain to the end. Cycle guard: a loop returns the start
    unchanged rather than picking an arbitrary point on the circle."""
    seen, cur = {target}, target
    while cur in by_path:
        nxt = by_path[cur]
        if nxt in seen:
            return target
        seen.add(nxt)
        cur = nxt
    return cur


def main() -> None:
    redirects = fetch_redirects()
    by_path = {r["path"]: r["target"] for r in redirects
               if r.get("path") and r.get("target")}
    chains = []
    for r in redirects:
        final = resolve(r.get("target", ""), by_path)
        if final and final != r.get("target"):
            chains.append((r, final))

    print(f"=== flatten_redirect_chains [{'APPLY' if APPLY else 'DRY-RUN'}] — "
          f"{len(redirects)} Redirects, {len(chains)} Kette(n) ===\n")
    if not chains:
        print("✅ Alle Redirects zeigen bereits auf ihr Endziel.")
        return
    ok = 0
    for r, final in chains:
        print(f"  {r['path'][:64]}")
        print(f"    {r['target'][:60]}  →  {final[:60]}")
        if not APPLY:
            continue
        try:
            resp = requests.put(f"{API}/redirects/{r['id']}.json",
                                headers=SHOPIFY_HEADERS, timeout=30,
                                json={"redirect": {"id": r["id"], "target": final}})
            resp.raise_for_status()
            ok += 1
        except Exception as e:
            print(f"    ✗ Update fehlgeschlagen: {str(e)[:80]}")
    print(f"\n{ok} geglättet." if APPLY else "\nDRY-RUN — mit --apply anwenden.")


if __name__ == "__main__":
    main()
