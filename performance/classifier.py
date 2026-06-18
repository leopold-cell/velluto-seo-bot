"""
Performance classifier (Phase 5).

Reads:
  - data/processed/gsc_performance.json   (from research/gsc_fetcher.py: per-page
    clicks/impressions deltas, striking-distance + emerging queries, low-CTR pages)
  - data/processed/existing_content_inventory.json  (decision/content_inventory.py)

Classifies EVERY URL on the domain into a tier. Phase 6 makes this REVENUE-aware:
if a page drove Shopify sales (via performance/conversions.py) it is ranked above
pure-click winners, because the goal is sales, not traffic.

  revenue_winner  drove real sales (28d)           → SCALE HARD (top priority)
  winner          real clicks AND growing          → SCALE  (cluster + internal links)
  rising          low base but strong momentum     → NURTURE (about to break out)
  decaying        used to get clicks, now dropping → REFRESH (update the page)
  dormant         lots of impressions, ~no clicks  → FIX CTR (meta/intent/refresh)
  steady          stable traffic                   → leave it

Pages with strong clicks but ZERO sales get a `traffic_no_sales` flag — an
intent/landing mismatch worth fixing rather than scaling.

Writes: data/processed/performance_feedback.json

This file is the contract the decision layer reads. opportunity_scorer.py turns
`scale_candidates` and `refresh_candidates` into scored actions so the bot
autonomously scales winners and fixes losers on the next run.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from collections import defaultdict
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GSC_PATH       = os.path.join(ROOT, "data", "processed", "gsc_performance.json")
INVENTORY_PATH = os.path.join(ROOT, "data", "processed", "existing_content_inventory.json")
CONV_PATH      = os.path.join(ROOT, "data", "processed", "conversion_performance.json")
OUTPUT_PATH    = os.path.join(ROOT, "data", "processed", "performance_feedback.json")

BLOG_PREFIX = "https://velluto-shop.com/blogs/velluto-the-magazine/"
HOMEPAGE    = "https://velluto-shop.com"   # brand/direct/ads baseline — not a scale target

# ── Tier thresholds (clicks + growth). Tweak here to tune aggressiveness. ────
WINNER_MIN_CLICKS        = 10    # meaningful traffic …
WINNER_MIN_GROWTH_PCT    = 15    # … and clearly growing
WINNER_ABS_CLICKS        = 25    # OR strong absolute clicks regardless of growth
RISING_MIN_IMPRESSIONS   = 50
RISING_MIN_CLICKS        = 2     # real engagement — rules out 0→1 click flukes
RISING_MIN_GROWTH_PCT    = 50    # clicks OR impressions momentum
RISING_MIN_IMPR_GROWTH   = 100
DECAY_MIN_PREV_CLICKS    = 8     # had real traffic to lose …
DECAY_MAX_GROWTH_PCT     = -30   # … and dropped hard
DORMANT_MIN_IMPRESSIONS  = 150   # very visible …
DORMANT_MAX_CLICKS       = 1     # … but nobody clicks
TRAFFIC_NO_SALES_CLICKS  = 20    # decent traffic but 0 orders → intent/landing mismatch


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _is_blog_post(url: str) -> bool:
    return url.startswith(BLOG_PREFIX) and url.rstrip("/") != BLOG_PREFIX.rstrip("/")


def _article_for_url(inventory: dict, url: str) -> dict | None:
    for a in (inventory.get("articles") or []):
        if (a.get("url") or "").rstrip("/") == url.rstrip("/"):
            return a
    return None


def _classify_one(d: dict) -> str:
    """Assign a tier to a single per-page delta record."""
    cc = d.get("curr_clicks", 0) or 0
    pc = d.get("prev_clicks", 0) or 0
    ci = d.get("curr_impressions", 0) or 0
    cg = d.get("clicks_delta_pct", 0) or 0
    ig = d.get("impr_delta_pct", 0) or 0

    # Order matters. Decaying first (real traffic falling off a cliff), then
    # winners, then dormant (very visible but unclicked — a CTR problem, NOT a
    # riser: a 0→1 click reads as +100% growth and must not count as momentum),
    # then genuine risers (need real clicks, ≥2, to rule out fluke single clicks).
    if pc >= DECAY_MIN_PREV_CLICKS and cg <= DECAY_MAX_GROWTH_PCT:
        return "decaying"
    if cc >= WINNER_ABS_CLICKS or (cc >= WINNER_MIN_CLICKS and cg >= WINNER_MIN_GROWTH_PCT):
        return "winner"
    if ci >= DORMANT_MIN_IMPRESSIONS and cc <= DORMANT_MAX_CLICKS:
        return "dormant"
    if (ci >= RISING_MIN_IMPRESSIONS
            and cc >= RISING_MIN_CLICKS
            and cc < WINNER_MIN_CLICKS
            and (cg >= RISING_MIN_GROWTH_PCT or ig >= RISING_MIN_IMPR_GROWTH)):
        return "rising"
    return "steady"


def classify(gsc: dict | None = None, inventory: dict | None = None,
             conversions: dict | None = None) -> dict:
    gsc = gsc if gsc is not None else _load(GSC_PATH)
    inventory = inventory if inventory is not None else _load(INVENTORY_PATH)
    conversions = conversions if conversions is not None else _load(CONV_PATH)
    today = _dt.date.today().isoformat()

    per_page = gsc.get("per_page_deltas") or []
    striking = gsc.get("striking_distance_queries") or []
    low_ctr  = gsc.get("low_ctr_pages") or []
    conv_by_page = (conversions or {}).get("by_page") or {}

    def _rev(url: str) -> dict:
        return conv_by_page.get(url.rstrip("/")) or conv_by_page.get(url) or {}

    # Map page → its striking-distance queries (the keywords to expand a winner around)
    queries_by_page: dict[str, list[dict]] = defaultdict(list)
    for q in striking:
        queries_by_page[q.get("page", "")].append({
            "query":        q.get("query"),
            "impressions":  q.get("impressions"),
            "avg_position": q.get("avg_position"),
        })

    tiers: dict[str, list[dict]] = {
        "revenue_winner": [], "winner": [], "rising": [], "decaying": [],
        "dormant": [], "steady": [],
    }

    for d in per_page:
        url = d.get("page", "")
        rev = _rev(url)
        revenue = rev.get("revenue", 0) or 0
        orders  = rev.get("orders", 0) or 0
        clicks  = d.get("curr_clicks", 0) or 0

        # Revenue overrides clicks: a page that sells is the real winner.
        if revenue > 0 or orders > 0:
            tier = "revenue_winner"
        else:
            tier = _classify_one(d)
        traffic_no_sales = (clicks >= TRAFFIC_NO_SALES_CLICKS and orders == 0)

        art = _article_for_url(inventory, url)
        rec = {
            "url":              url,
            "is_blog_post":     _is_blog_post(url),
            "tier":             tier,
            "curr_clicks":      clicks,
            "prev_clicks":      d.get("prev_clicks", 0),
            "clicks_delta_pct": d.get("clicks_delta_pct", 0),
            "curr_impressions": d.get("curr_impressions", 0),
            "impr_delta_pct":   d.get("impr_delta_pct", 0),
            "orders":           orders,
            "revenue":          revenue,
            "prev_revenue":     rev.get("prev_revenue", 0) or 0,
            "traffic_no_sales": traffic_no_sales,
            "article_id":       (art or {}).get("id"),
            "handle":           (art or {}).get("handle"),
            "title":            (art or {}).get("title"),
            "primary_keyword":  (art or {}).get("primary_keyword"),
            "top_queries":      queries_by_page.get(url, [])[:5],
        }
        tiers[tier].append(rec)

    # Sort each tier by what matters for it
    tiers["revenue_winner"].sort(key=lambda r: (r["revenue"], r["curr_clicks"]), reverse=True)
    tiers["winner"].sort(key=lambda r: r["curr_clicks"], reverse=True)
    tiers["rising"].sort(key=lambda r: r["impr_delta_pct"], reverse=True)
    tiers["decaying"].sort(key=lambda r: r["clicks_delta_pct"])           # worst first
    tiers["dormant"].sort(key=lambda r: r["curr_impressions"], reverse=True)

    # ── Build action candidates the scorer consumes ──────────────────────────
    # SCALE: revenue winners first (proven to sell), then click winners + risers →
    # expand the cluster around the queries the page already ranks for + internal links.
    scale_candidates: list[dict] = []
    for r in tiers["revenue_winner"] + tiers["winner"] + tiers["rising"]:
        # Homepage revenue is mostly brand/direct/ads — never scale it as a content cluster.
        if r["url"].rstrip("/") == HOMEPAGE:
            continue
        scale_queries = [q["query"] for q in r["top_queries"] if q.get("query")]
        scale_candidates.append({
            "url":             r["url"],
            "tier":            r["tier"],
            "title":           r["title"],
            "primary_keyword": r["primary_keyword"],
            "curr_clicks":     r["curr_clicks"],
            "clicks_delta_pct": r["clicks_delta_pct"],
            "revenue":         r["revenue"],
            "orders":          r["orders"],
            "scale_queries":   scale_queries,
            "is_blog_post":    r["is_blog_post"],
        })

    # REFRESH: decayers (priority), dormant (CTR problem), and pages with traffic
    # but no sales (intent/landing mismatch — fix the bridge to product).
    refresh_candidates: list[dict] = []
    for r in tiers["decaying"]:
        refresh_candidates.append({**_refresh_rec(r), "reason": "decaying"})
    for r in tiers["dormant"]:
        refresh_candidates.append({**_refresh_rec(r), "reason": "dormant_low_ctr"})
    traffic_no_sales = [r for t in tiers.values() for r in t if r.get("traffic_no_sales")]
    traffic_no_sales.sort(key=lambda r: r["curr_clicks"], reverse=True)
    for r in traffic_no_sales:
        if r["tier"] not in ("decaying", "dormant"):  # avoid dupes
            refresh_candidates.append({**_refresh_rec(r), "reason": "traffic_no_sales"})

    # Low-CTR query/page pairs straight from GSC (fast meta wins for meta_optimizer).
    low_ctr_targets = [
        {"query": x.get("query"), "page": x.get("page"),
         "impressions": x.get("impressions"), "ctr_pct": x.get("ctr_pct"),
         "avg_position": x.get("avg_position")}
        for x in low_ctr
    ]

    gsc_totals = gsc.get("totals") or {}
    conv_totals = (conversions or {}).get("totals") or {}
    result = {
        "date":     today,
        "windows":  gsc.get("windows") or {},
        "totals":   gsc_totals,
        "conversion_totals": conv_totals,
        "counts": {
            "revenue_winner": len(tiers["revenue_winner"]),
            "winner":   len(tiers["winner"]),
            "rising":   len(tiers["rising"]),
            "decaying": len(tiers["decaying"]),
            "dormant":  len(tiers["dormant"]),
            "steady":   len(tiers["steady"]),
            "traffic_no_sales": len(traffic_no_sales),
            "pages_evaluated": len(per_page),
        },
        "tiers":              tiers,
        "scale_candidates":   scale_candidates,
        "refresh_candidates": refresh_candidates,
        "low_ctr_targets":    low_ctr_targets,
        "gsc_available":      bool(per_page),
        "conversions_available": bool(conv_by_page),
    }
    return result


def _refresh_rec(r: dict) -> dict:
    return {
        "url":              r["url"],
        "tier":             r["tier"],
        "title":            r["title"],
        "primary_keyword":  r["primary_keyword"],
        "curr_clicks":      r["curr_clicks"],
        "prev_clicks":      r["prev_clicks"],
        "clicks_delta_pct": r["clicks_delta_pct"],
        "curr_impressions": r["curr_impressions"],
        "orders":           r.get("orders", 0),
        "revenue":          r.get("revenue", 0),
        "is_blog_post":     r["is_blog_post"],
    }


def _save(payload: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def run() -> dict:
    """Load GSC + inventory + conversions from disk, classify, persist feedback json."""
    result = classify()
    _save(result)
    c = result["counts"]
    if not result["gsc_available"]:
        print("   ⚠️  Performance: gsc_performance.json empty — no feedback (check GSC creds / property).")
    else:
        rev = result.get("conversion_totals", {}).get("revenue", 0)
        print(f"   ✓ Performance: {c['revenue_winner']} revenue-winners, {c['winner']} click-winners, "
              f"{c['rising']} rising, {c['decaying']} decaying, {c['dormant']} dormant, "
              f"{c['traffic_no_sales']} traffic-no-sales "
              f"({c['pages_evaluated']} pages, 28d revenue {rev})")
    return result


def load_feedback() -> dict:
    """Cheap read for the scorer; returns {} if not built yet."""
    return _load(OUTPUT_PATH)


if __name__ == "__main__":
    res = run()
    print(json.dumps({"counts": res["counts"],
                      "scale": [c["url"] for c in res["scale_candidates"][:5]],
                      "refresh": [c["url"] for c in res["refresh_candidates"][:5]]},
                     indent=2, ensure_ascii=False))
