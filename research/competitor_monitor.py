"""
Competitor sitemap monitor.

For each competitor in config/competitors.yml:
  1. Fetch its sitemap.xml (timeout 10s).
  2. If it's a <sitemapindex>, follow up to 5 child sitemaps.
  3. Collect all URLs.
  4. Diff against data/snapshots/competitors_last.json.
  5. For each new URL (cap: top 5 per competitor), call fetch_page_intel().

Failures are warnings, never aborts.

Output: data/processed/competitor_new_topics.json
Snapshot: data/snapshots/competitors_last.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import requests

import config_loader

# Reuse the page-intel parser from existing code
from seo_optimizer import fetch_page_intel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH   = os.path.join(ROOT, "data", "processed", "competitor_new_topics.json")
SNAPSHOT_PATH = os.path.join(ROOT, "data", "snapshots", "competitors_last.json")

MAX_NESTED_SITEMAPS  = 5
MAX_NEW_URLS_TO_INTEL = 5
MAX_TOTAL_URLS_PER_COMP = 500  # avoid memory blowup on huge sitemaps
HTTP_TIMEOUT = 10


def _fetch_sitemap(url: str) -> list[str]:
    """Return list of URLs (from <url><loc>) or list of sub-sitemap URLs (from <sitemap><loc>)."""
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; VellutoBot/1.0)"})
        if r.status_code != 200:
            return []
        # Strip XML namespace for easier parsing
        xml_text = re.sub(r'\sxmlns="[^"]+"', "", r.text, count=1)
        root = ET.fromstring(xml_text)
    except Exception as e:
        print(f"      ⚠️  sitemap fetch failed: {url}: {e}")
        return []

    # sitemap-index vs urlset — handle both
    locs: list[str] = []
    for loc in root.findall(".//loc"):
        if loc.text:
            locs.append(loc.text.strip())
    return locs[:MAX_TOTAL_URLS_PER_COMP]


def _is_sitemap_index(urls: list[str]) -> bool:
    """Heuristic: if most URLs end in .xml or contain 'sitemap', it's an index."""
    if not urls:
        return False
    xml_count = sum(1 for u in urls if u.endswith(".xml") or "sitemap" in u.lower())
    return xml_count > len(urls) * 0.5


def _collect_urls(competitor: dict) -> list[str]:
    """Fetch top sitemap + follow 1 level of sub-sitemaps if it's an index."""
    sm_url = competitor.get("sitemap")
    if not sm_url:
        return []
    urls = _fetch_sitemap(sm_url)
    if _is_sitemap_index(urls):
        # Follow up to 5 child sitemaps
        all_urls: list[str] = []
        for child in urls[:MAX_NESTED_SITEMAPS]:
            child_urls = _fetch_sitemap(child)
            # Only add non-sitemap URLs (final pages)
            all_urls.extend([u for u in child_urls if not u.endswith(".xml")])
            if len(all_urls) >= MAX_TOTAL_URLS_PER_COMP:
                break
        return all_urls[:MAX_TOTAL_URLS_PER_COMP]
    return urls


def _load_snapshot() -> dict[str, list[str]]:
    if not os.path.exists(SNAPSHOT_PATH):
        return {}
    try:
        with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_snapshot(snapshot: dict[str, list[str]]) -> None:
    os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)


def run() -> dict:
    competitors = config_loader.competitors().get("core_competitors", [])
    prev_snapshot = _load_snapshot()
    today = _dt.date.today().isoformat()

    new_snapshot: dict[str, list[str]] = {}
    new_topics_per_competitor: list[dict] = []
    total_new = 0
    total_pages_inspected = 0
    is_first_run = not prev_snapshot

    for comp in competitors:
        name   = comp["name"]
        domain = comp["domain"]
        print(f"   [{name}] fetching sitemap…", flush=True)
        urls = _collect_urls(comp)
        new_snapshot[domain] = urls

        if is_first_run:
            print(f"      first snapshot — {len(urls)} URLs captured (no diff yet)")
            continue

        prev_urls = set(prev_snapshot.get(domain, []))
        new_urls = [u for u in urls if u not in prev_urls]
        if not new_urls:
            print(f"      no new URLs (total {len(urls)})")
            continue

        # Inspect top N new URLs
        intel_for: list[dict] = []
        for u in new_urls[:MAX_NEW_URLS_TO_INTEL]:
            page = fetch_page_intel(u)
            if page:
                intel_for.append(page)
                total_pages_inspected += 1

        new_topics_per_competitor.append({
            "competitor":      name,
            "domain":          domain,
            "new_url_count":   len(new_urls),
            "new_urls_sample": new_urls[:MAX_NEW_URLS_TO_INTEL],
            "page_intel":      intel_for,
            "first_seen":      today,
        })
        total_new += len(new_urls)
        print(f"      ✓ {len(new_urls)} new URLs ({len(intel_for)} inspected)")

    _save_snapshot(new_snapshot)

    result = {
        "date":                  today,
        "is_first_run":          is_first_run,
        "total_new_urls":        total_new,
        "pages_inspected":       total_pages_inspected,
        "new_topics_per_competitor": new_topics_per_competitor,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    if is_first_run:
        print(f"   ✓ Competitor monitor: first run — {sum(len(v) for v in new_snapshot.values())} "
              f"URLs snapshotted across {len(new_snapshot)} competitors")
    else:
        print(f"   ✓ Competitor monitor: {total_new} new URLs across {len(new_topics_per_competitor)} competitors "
              f"({total_pages_inspected} pages inspected)")
    return result


if __name__ == "__main__":
    print(json.dumps({k: v for k, v in run().items() if k != "new_topics_per_competitor"}, indent=2))
