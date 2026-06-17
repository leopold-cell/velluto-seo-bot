"""
Per-article performance audit (did the posts work?).

Reuses research/gsc_fetcher.run() output (data/processed/gsc_performance.json),
which already pulls per-page clicks/impressions/position for the last 28 days
vs the previous 28 days. Maps each article URL to its GSC page metrics and
classifies it: dead / weak / low_ctr / performing.
"""
from __future__ import annotations

import json
import os

from review._common import ROOT, review_config

PERF_PATH = os.path.join(ROOT, "data", "processed", "gsc_performance.json")


def refresh_gsc_performance() -> bool:
    """Run the per-page GSC fetcher. Returns True on success. Safe to call —
    no-ops (returns False) if GSC credentials are missing."""
    try:
        from research import gsc_fetcher
        gsc_fetcher.run()
        return True
    except Exception as e:
        print(f"   ⚠️  performance: GSC refresh failed: {e}")
        return False


def _load_performance() -> dict:
    if os.path.exists(PERF_PATH):
        try:
            return json.load(open(PERF_PATH))
        except Exception:
            return {}
    return {}


def audit(articles: list[dict]) -> dict:
    cfg = review_config()
    dead_thr = cfg["dead_post_impressions_threshold"]
    weak_thr = cfg["weak_post_impressions_threshold"]

    perf = _load_performance()
    by_url = {row["page"]: row for row in perf.get("per_page_deltas", [])}
    low_ctr_pages = {row["page"] for row in perf.get("low_ctr_pages", [])}

    results: list[dict] = []
    buckets = {"dead": 0, "weak": 0, "low_ctr": 0, "performing": 0, "no_data": 0}

    for a in articles:
        row = by_url.get(a["url"])
        if not row:
            # Not in top-N per-page rows → effectively no measurable traffic.
            bucket = "no_data"
            entry = {"curr_impressions": 0, "curr_clicks": 0}
        else:
            impr = row.get("curr_impressions", 0)
            entry = row
            if impr <= dead_thr:
                bucket = "dead"
            elif impr < weak_thr:
                bucket = "weak"
            elif a["url"] in low_ctr_pages:
                bucket = "low_ctr"
            else:
                bucket = "performing"
        buckets[bucket] += 1
        results.append({
            "handle": a["handle"],
            "url": a["url"],
            "published_at": a.get("published_at"),
            "bucket": bucket,
            "curr_impressions": entry.get("curr_impressions", 0),
            "curr_clicks": entry.get("curr_clicks", 0),
            "impr_delta_pct": entry.get("impr_delta_pct"),
            "clicks_delta_pct": entry.get("clicks_delta_pct"),
        })

    results.sort(key=lambda r: r["curr_impressions"], reverse=True)
    return {
        "window": perf.get("windows", {}).get("current"),
        "totals": perf.get("totals", {}),
        "buckets": buckets,
        "articles_checked": len(results),
        "has_gsc_data": bool(by_url),
        "results": results,
    }
