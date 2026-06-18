"""
GSC fetcher — extends seo_optimizer.fetch_gsc().

Adds:
  - per-page baseline (prev 28d) vs current (last 28d)
  - striking-distance queries (pos 8-25, impr >= 50)
  - emerging queries (+100% impressions vs prev period)
  - cannibalization candidates (same query, multiple Velluto URLs)
  - low-CTR pages (pos <= 10 AND ctr < expected)

Output: data/processed/gsc_performance.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import urllib.parse
from collections import defaultdict
from typing import Any

import requests

from seo_optimizer import _gsc_token, GSC_SITE_URL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(ROOT, "data", "processed", "gsc_performance.json")


def _query_gsc(token: str, start: str, end: str, dimensions: list[str],
               row_limit: int = 500) -> list[dict]:
    site = urllib.parse.quote(GSC_SITE_URL, safe="")
    try:
        r = requests.post(
            f"https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"startDate": start, "endDate": end,
                  "dimensions": dimensions, "rowLimit": row_limit},
            timeout=20,
        )
        return r.json().get("rows", [])
    except Exception as e:
        print(f"      ⚠️  GSC query error ({dimensions}): {e}")
        return []


def _row_key(row: dict) -> tuple:
    return tuple(row.get("keys", []))


def _diff_metric(curr: float, prev: float) -> float:
    """Return % delta. prev=0 → 100 if curr>0, else 0."""
    if prev == 0:
        return 100.0 if curr > 0 else 0.0
    return round((curr - prev) / prev * 100.0, 1)


# Real content paths that must NOT be mistaken for a locale prefix.
_NON_LOCALE_SEG = {"blogs", "products", "pages", "collections", "cdn", "discount",
                   "cart", "checkout", "account", "tools", "apps", "a"}


def _norm_url(url: str) -> str:
    """Strip a leading locale prefix (/nl/, /en-eu/, /de/) so the same article on
    different language paths aggregates into ONE row. Phase 6.1 data-quality fix."""
    try:
        p = urllib.parse.urlparse(url)
        parts = p.path.split("/")
        if (len(parts) > 1 and 2 <= len(parts[1]) <= 5
                and parts[1].replace("-", "").isalpha()
                and parts[1].lower() == parts[1]
                and parts[1] not in _NON_LOCALE_SEG):
            path = "/" + "/".join(parts[2:])
        else:
            path = p.path
        path = path.rstrip("/") or "/"
        return f"{p.scheme}://{p.netloc}{path}"
    except Exception:
        return url


def run() -> dict:
    today = _dt.date.today()
    today_iso = today.isoformat()
    result_empty = {
        "date": today_iso,
        "striking_distance_queries": [],
        "emerging_queries": [],
        "low_ctr_pages": [],
        "cannibalization_candidates": [],
        "per_page_deltas": [],
        "totals": {},
    }

    token = _gsc_token()
    if not token:
        print("   ⚠️  GSC: credentials missing — skipping")
        _save(result_empty)
        return result_empty

    curr_end   = today_iso
    curr_start = (today - _dt.timedelta(days=28)).isoformat()
    prev_end   = (today - _dt.timedelta(days=29)).isoformat()
    prev_start = (today - _dt.timedelta(days=56)).isoformat()

    print(f"   GSC: pulling current ({curr_start}→{curr_end}) and previous ({prev_start}→{prev_end})…")

    # 1. Striking-distance + low-CTR: query+page dimensions, current window
    curr_qp = _query_gsc(token, curr_start, curr_end, ["query", "page"], row_limit=1000)

    # 2. Per-page deltas: page dimension, both windows
    curr_p = _query_gsc(token, curr_start, curr_end, ["page"], row_limit=500)
    prev_p = _query_gsc(token, prev_start, prev_end, ["page"], row_limit=500)

    # 3. Emerging queries: query dim, both windows
    curr_q = _query_gsc(token, curr_start, curr_end, ["query"], row_limit=500)
    prev_q = _query_gsc(token, prev_start, prev_end, ["query"], row_limit=500)

    # --- Striking-distance + low-CTR ---
    striking_distance: list[dict] = []
    low_ctr_pages:     list[dict] = []
    for row in curr_qp:
        kw, page = row["keys"][0], _norm_url(row["keys"][1])
        impr = row.get("impressions", 0) or 0
        clks = row.get("clicks", 0) or 0
        ctr  = row.get("ctr", 0) or 0
        pos  = row.get("position", 99) or 99

        if 8 <= pos <= 25 and impr >= 50:
            striking_distance.append({
                "query":         kw,
                "page":          page,
                "impressions":   int(impr),
                "clicks":        int(clks),
                "ctr_pct":       round(ctr * 100, 2),
                "avg_position":  round(pos, 1),
            })
        if pos <= 10 and impr >= 100 and ctr < 0.03:
            low_ctr_pages.append({
                "query":        kw,
                "page":         page,
                "impressions":  int(impr),
                "ctr_pct":      round(ctr * 100, 2),
                "avg_position": round(pos, 1),
            })

    striking_distance.sort(key=lambda x: x["impressions"], reverse=True)
    low_ctr_pages.sort(key=lambda x: x["impressions"], reverse=True)

    # --- Cannibalization: same query, multiple Velluto pages ---
    by_query: dict[str, list[dict]] = defaultdict(list)
    for row in curr_qp:
        kw, page = row["keys"][0], _norm_url(row["keys"][1])
        impr = row.get("impressions", 0) or 0
        if impr >= 10:
            by_query[kw].append({"page": page, "impressions": int(impr),
                                 "position": round(row.get("position", 99), 1)})
    cannibalization = [
        {"query": kw, "pages": pages}
        for kw, pages in by_query.items()
        if len(pages) >= 2
    ]
    cannibalization.sort(key=lambda x: sum(p["impressions"] for p in x["pages"]), reverse=True)
    cannibalization = cannibalization[:20]

    # --- Per-page deltas (aggregated by locale-normalized URL) ---
    def _agg_pages(rows: list[dict]) -> dict[str, dict]:
        agg: dict[str, dict] = defaultdict(lambda: {"impressions": 0.0, "clicks": 0.0})
        for r in rows:
            u = _norm_url(r["keys"][0])
            agg[u]["impressions"] += r.get("impressions", 0) or 0
            agg[u]["clicks"]      += r.get("clicks", 0) or 0
        return agg

    curr_agg = _agg_pages(curr_p)
    prev_agg = _agg_pages(prev_p)
    per_page_deltas: list[dict] = []
    for page, cv in curr_agg.items():
        curr_impr = cv["impressions"]
        curr_clks = cv["clicks"]
        pv = prev_agg.get(page, {"impressions": 0, "clicks": 0})
        prev_impr = pv["impressions"]
        prev_clks = pv["clicks"]
        if curr_impr < 5 and prev_impr < 5:
            continue
        per_page_deltas.append({
            "page":            page,
            "curr_impressions": int(curr_impr),
            "prev_impressions": int(prev_impr),
            "impr_delta_pct":   _diff_metric(curr_impr, prev_impr),
            "curr_clicks":      int(curr_clks),
            "prev_clicks":      int(prev_clks),
            "clicks_delta_pct": _diff_metric(curr_clks, prev_clks),
        })
    per_page_deltas.sort(key=lambda x: abs(x["impr_delta_pct"]), reverse=True)
    per_page_deltas = per_page_deltas[:50]

    # --- Emerging queries ---
    prev_q_map = {r["keys"][0]: r.get("impressions", 0) for r in prev_q}
    emerging: list[dict] = []
    for r in curr_q:
        kw = r["keys"][0]
        curr_impr = r.get("impressions", 0) or 0
        prev_impr = prev_q_map.get(kw, 0) or 0
        if curr_impr < 20:
            continue
        delta = _diff_metric(curr_impr, prev_impr)
        if delta >= 100:
            emerging.append({
                "query":            kw,
                "curr_impressions": int(curr_impr),
                "prev_impressions": int(prev_impr),
                "impr_delta_pct":   delta,
                "avg_position":     round(r.get("position", 99), 1),
            })
    emerging.sort(key=lambda x: x["impr_delta_pct"], reverse=True)
    emerging = emerging[:30]

    # --- Totals ---
    totals = {
        "curr_impressions": int(sum(r.get("impressions", 0) or 0 for r in curr_p)),
        "curr_clicks":      int(sum(r.get("clicks", 0) or 0 for r in curr_p)),
        "prev_impressions": int(sum(r.get("impressions", 0) or 0 for r in prev_p)),
        "prev_clicks":      int(sum(r.get("clicks", 0) or 0 for r in prev_p)),
    }
    totals["impr_delta_pct"]   = _diff_metric(totals["curr_impressions"], totals["prev_impressions"])
    totals["clicks_delta_pct"] = _diff_metric(totals["curr_clicks"],      totals["prev_clicks"])

    result = {
        "date":                       today_iso,
        "windows":                    {"current": [curr_start, curr_end],
                                        "previous": [prev_start, prev_end]},
        "striking_distance_queries":  striking_distance[:30],
        "emerging_queries":           emerging,
        "low_ctr_pages":              low_ctr_pages[:20],
        "cannibalization_candidates": cannibalization,
        "per_page_deltas":            per_page_deltas,
        "totals":                     totals,
    }
    _save(result)
    print(f"   ✓ GSC: {len(striking_distance)} striking-distance, "
          f"{len(emerging)} emerging, {len(low_ctr_pages)} low-CTR, "
          f"{len(cannibalization)} cannibalization, {len(per_page_deltas)} per-page deltas "
          f"(total Δ impressions: {totals['impr_delta_pct']:+.1f}%)")
    return result


def _save(payload: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    result = run()
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("per_page_deltas", "striking_distance_queries",
                                   "emerging_queries", "low_ctr_pages",
                                   "cannibalization_candidates")}, indent=2))
