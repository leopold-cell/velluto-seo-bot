"""
SERP fetcher — DataForSEO Live Advanced.

Calls POST https://api.dataforseo.com/v3/serp/google/organic/live/advanced for
each (keyword × market) due today by cadence. Stores the FULL response so
paa_extractor.py and ai_overview_monitor.py can parse it without refetching.

Cadence (defined in config/markets.yml `serp_cadence`):
  - daily          (US, DE, NL)         → every run
  - every_3_days   (FR, ES, IT)         → when day_of_year % 3 == 0
  - weekly         (DA, NB, PL, PT, SV) → Mondays only

Budget: ~$0.002/SERP. With 10 seed keywords:
  - daily markets: 30 SERPs/day → $1.80/mo
  - every-3-days:   10/day avg  → $0.60/mo
  - weekly:          7/day avg  → $0.43/mo
  - total:                       ~$2.83/mo

Output: data/processed/serp_snapshots.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

import config_loader

load_dotenv(
    dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    override=True,
)

DATAFORSEO_LOGIN = os.getenv("DATAFORSEO_LOGIN", "")
DATAFORSEO_PASS  = os.getenv("DATAFORSEO_PASSWORD", "")
BASE             = "https://api.dataforseo.com/v3"
OUTPUT_PATH      = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "processed", "serp_snapshots.json",
)


def markets_due_today() -> list[str]:
    """Return market codes whose SERPs should be fetched today, per cadence."""
    today  = _dt.date.today()
    is_mon = today.weekday() == 0
    day_n  = today.timetuple().tm_yday
    out: list[str] = []
    for code, m in config_loader.markets().items():
        cad = m.get("serp_cadence", "weekly")
        if cad == "daily":
            out.append(code)
        elif cad == "every_3_days" and day_n % 3 == 0:
            out.append(code)
        elif cad == "weekly" and is_mon:
            out.append(code)
    return out


def _seed_keywords() -> list[str]:
    """
    Merged keyword pool: solution-framed (Phase 2) + problem-framed (Phase 4.5).
    DataForSEO + the opportunity scorer filter for what's worth pursuing.
    """
    cfg = config_loader.get("seed_keywords")
    solution = cfg.get("phase2_seed_keywords", []) or []
    problem  = cfg.get("phase4_5_problem_keywords", []) or []
    # Dedupe preserving order — solution keywords first (existing priority)
    seen, merged = set(), []
    for kw in solution + problem:
        if kw and kw.lower() not in seen:
            seen.add(kw.lower())
            merged.append(kw)
    return merged


def fetch_one(keyword: str, market_code: str) -> dict | None:
    """
    Fetch one SERP. Returns the full DataForSEO `tasks[0].result[0]` object,
    or None on any failure (no exception bubbles up — caller must handle None).
    """
    if not DATAFORSEO_LOGIN or not DATAFORSEO_PASS:
        return None
    m = config_loader.market(market_code)
    if not m:
        return None
    try:
        r = requests.post(
            f"{BASE}/serp/google/organic/live/advanced",
            json=[{
                "keyword":       keyword,
                "language_code": m["language_code"],
                "location_code": m["dataforseo_location_code"],
                "device":        "desktop",
                "os":            "windows",
                "depth":         10,
            }],
            auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASS),
            timeout=45,
        )
        r.raise_for_status()
        tasks = r.json().get("tasks") or []
        if not tasks:
            return None
        results = tasks[0].get("result") or []
        return results[0] if results else None
    except Exception as e:
        print(f"      ⚠️  SERP fetch failed for '{keyword}' [{market_code}]: {e}")
        return None


def run() -> dict:
    """
    Main entrypoint. Returns:
      {
        "date":          "YYYY-MM-DD",
        "markets_fetched": ["US", "DE", "NL"],
        "keywords":      [...],
        "snapshots":     [{market, keyword, organic, paa, related, ai_overview, raw_items_count}],
        "cost_usd":      0.06,
        "errors":        N,
      }
    """
    today = _dt.date.today().isoformat()
    markets = markets_due_today()
    keywords = _seed_keywords()

    if not markets or not keywords:
        print(f"   SERP: nothing to fetch today (markets={markets}, keywords={len(keywords)})")
        result = {"date": today, "markets_fetched": markets, "keywords": keywords,
                  "snapshots": [], "cost_usd": 0.0, "errors": 0}
        _save(result)
        return result

    snapshots = []
    errors = 0
    print(f"   SERP: fetching {len(keywords)} keywords × {len(markets)} markets "
          f"= {len(keywords) * len(markets)} SERPs (~${len(keywords)*len(markets)*0.002:.2f})")

    for kw in keywords:
        for mc in markets:
            res = fetch_one(kw, mc)
            if res is None:
                errors += 1
                continue
            items = res.get("items") or []
            organic = [i for i in items if i.get("type") == "organic"]
            paa     = [i for i in items if i.get("type") == "people_also_ask"]
            related = [i for i in items if i.get("type") == "related_searches"]
            ai_ovr  = [i for i in items if i.get("type") == "ai_overview"]
            snapshots.append({
                "market":          mc,
                "keyword":         kw,
                "organic":         organic[:10],
                "people_also_ask": paa,
                "related":         related,
                "ai_overview":     ai_ovr[0] if ai_ovr else None,
                "raw_items_count": len(items),
            })
            # Be polite to the API — small delay between calls
            time.sleep(0.2)

    result = {
        "date":            today,
        "markets_fetched": markets,
        "keywords":        keywords,
        "snapshots":       snapshots,
        "cost_usd":        round(len(snapshots) * 0.002, 4),
        "errors":          errors,
    }
    _save(result)
    print(f"   ✓ SERP: {len(snapshots)} snapshots saved ({errors} errors, ~${result['cost_usd']})")
    return result


def _save(payload: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_latest() -> dict | None:
    """Read back the most-recent serp_snapshots.json. Used by paa/aio extractors."""
    if not os.path.exists(OUTPUT_PATH):
        return None
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    print(f"Markets due today: {markets_due_today()}")
    print(f"Seed keywords: {len(_seed_keywords())}")
    result = run()
    print(json.dumps({k: v for k, v in result.items() if k != "snapshots"}, indent=2))
