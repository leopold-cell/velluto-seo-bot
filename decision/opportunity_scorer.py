"""
Opportunity scorer — implements the formula from spec line 1093-1114.

Final formula (weights from config/scoring_weights.yml):
  opportunity_score =
      buyer_intent_score        * 0.30
    + product_fit_score         * 0.25
    + competitor_velocity_score * 0.15
    + keyword_demand_score      * 0.10
    + serp_weakness_score       * 0.10
    + localization_potential    * 0.05
    + internal_link_value       * 0.05

Each sub-score is 0-100. Final score is 0-100.

Candidate sources (Phase 3 MVP):
  1. Each seed keyword (one candidate per keyword, scored against US SERP as canonical)
  2. Each GSC striking-distance query (becomes "update_existing_article" candidate)

Output: data/processed/opportunity_scores.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any

import config_loader
from decision.content_inventory import find_matching_article

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(ROOT, "data", "processed", "opportunity_scores.json")


# ── Sub-scorers ────────────────────────────────────────────────────────────

def score_buyer_intent(keyword: str) -> int:
    """Classify keyword against buyer_intent_rules.yml. Returns 0-100."""
    rules = config_loader.buyer_intent_rules().get("buyer_intent_classes", {})
    kw = keyword.lower()
    # Heuristic: check very_high → high → medium → low based on keyword tokens
    if any(t in kw for t in ["best ", "alternative", " vs ", "worth it", "review",
                              "anti fog", "anti-fog", "with interchangeable"]):
        return rules.get("very_high", {}).get("min_score", 80) + 10  # → 90
    if any(t in kw for t in ["for wind", "for watery", "uv400", "photochromic",
                              "for changing", "for road bike", "for gravel"]):
        return rules.get("high", {}).get("min_score", 65) + 10  # → 75
    if any(t in kw for t in ["what color", "are polarized", "why do", "how should",
                              "what is", "what are"]):
        return rules.get("medium", {}).get("min_score", 50) + 10  # → 60
    if any(t in kw for t in ["cycling style", "tour de france", "tips"]):
        return 30
    # Default for "cycling sunglasses", "cycling glasses" — commercial category
    return 70


def score_product_fit(keyword: str) -> int:
    """Match keyword tokens against velluto_positioning.product_fit."""
    pf = config_loader.velluto_positioning().get("product_fit", {})
    kw = keyword.lower()
    best = 0
    for category, data in pf.items():
        priority = data.get("priority", 5)
        if any(k.lower() in kw for k in data.get("keywords", [])):
            # Priority 10 → 100, priority 5 → 50
            score = priority * 10
            if score > best:
                best = score
    # Anything cycling-related gets a baseline of 60
    if best == 0 and any(t in kw for t in ["cycling", "road bike", "gravel", "rennrad", "fietsen"]):
        best = 60
    return min(100, best)


def score_serp_weakness(snapshot: dict) -> int:
    """
    Heuristic SERP weakness based on what we see in organic + AI Overview:
      - If competitor brands dominate top 3 → SERP is "strong" (low weakness)
      - If forum/reddit/generic mags dominate → SERP is "weak" (high weakness)
      - If AI Overview cites no big brands → also weak
    """
    if not snapshot:
        return 50  # neutral
    organic = snapshot.get("organic") or []
    forbidden = config_loader.forbidden_outbound_domains()
    competitor_in_top3 = sum(
        1 for o in organic[:3]
        if any(d in (o.get("domain") or "").lower() for d in forbidden)
    )
    if competitor_in_top3 >= 2:
        return 30  # crowded with established brands
    if competitor_in_top3 == 1:
        return 55
    # No competitors in top 3 → opportunity
    return 75


def score_keyword_demand(volume: int | None) -> int:
    """Map DataForSEO monthly search volume → 0-100."""
    if not volume:
        return 30
    if volume >= 10000: return 100
    if volume >= 5000:  return 90
    if volume >= 2000:  return 80
    if volume >= 1000:  return 70
    if volume >= 500:   return 60
    if volume >= 200:   return 50
    if volume >= 50:    return 40
    return 30


def score_competitor_velocity(competitors_bundle: dict, keyword: str) -> int:
    """If competitors recently published pages matching this keyword's topic → high velocity."""
    if not competitors_bundle:
        return 50
    kw_tokens = set(re.findall(r"\w+", keyword.lower()))
    new_topics = competitors_bundle.get("new_topics_per_competitor", []) or []
    hits = 0
    for c in new_topics:
        for page in (c.get("page_intel") or []):
            title = (page.get("title") or "").lower()
            t_tokens = set(re.findall(r"\w+", title))
            overlap = kw_tokens & t_tokens
            if len(overlap) >= max(2, len(kw_tokens) - 2):
                hits += 1
    if hits >= 3: return 90
    if hits == 2: return 70
    if hits == 1: return 55
    return 40


def score_localization_potential(keyword: str, serps_bundle: dict) -> int:
    """How many markets fetched a SERP for this keyword today."""
    if not serps_bundle:
        return 50
    matching = sum(
        1 for s in (serps_bundle.get("snapshots") or [])
        if s.get("keyword", "").lower() == keyword.lower()
    )
    if matching >= 3: return 90
    if matching == 2: return 70
    if matching == 1: return 50
    return 30


def score_internal_link_value(keyword: str, inventory: dict) -> int:
    """High if Velluto has related (but not duplicate) content to link FROM."""
    if not inventory:
        return 50
    kw_tokens = set(re.findall(r"\w+", keyword.lower()))
    related = 0
    duplicate = False
    for a in inventory.get("articles", []):
        title_tokens = set(re.findall(r"\w+", (a.get("title") or "").lower()))
        overlap = len(kw_tokens & title_tokens)
        if overlap >= max(3, len(kw_tokens) - 1):
            duplicate = True
        elif overlap >= 1:
            related += 1
    if duplicate:
        return 30  # cannibalization risk
    if related >= 5: return 90
    if related >= 2: return 75
    if related >= 1: return 60
    return 40


# ── AI Overview boost ──────────────────────────────────────────────────────

def score_ai_overview(ai_overviews_bundle: dict, keyword: str) -> int:
    """If AI Overview exists for this keyword + Velluto isn't cited → high opportunity."""
    if not ai_overviews_bundle:
        return 50
    for aio in (ai_overviews_bundle.get("ai_overviews") or []):
        if aio.get("keyword", "").lower() == keyword.lower():
            score = 50
            if aio.get("ai_overview_present"):
                score = 70
            if aio.get("velluto_gap"):
                score = 85
            if aio.get("competitor_cited"):
                score += 5
            return min(100, score)
    return 50


# ── Final scorer ───────────────────────────────────────────────────────────

def _aggregate(scores: dict[str, int]) -> float:
    w = config_loader.scoring_weights()["weights"]
    return round(
        scores["buyer_intent"]        * w["buyer_intent"]
        + scores["product_fit"]       * w["product_fit"]
        + scores["competitor_velocity"]*w["competitor_velocity"]
        + scores["keyword_demand"]    * w["keyword_demand"]
        + scores["serp_weakness"]     * w["serp_weakness"]
        + scores["localization_potential"] * w["localization_potential"]
        + scores["internal_link_value"]    * w["internal_link_value"],
        2,
    )


def score(research: dict, inventory: dict) -> dict:
    """
    Score every candidate opportunity. Returns:
      {
        date, candidates: [...sorted by opportunity_score desc...],
        total_candidates, max_score
      }
    """
    serps_bundle      = research.get("serps") or {}
    paa_bundle        = research.get("paa") or {}
    aio_bundle        = research.get("ai_overviews") or {}
    competitors_bundle = research.get("competitors") or {}
    gsc_bundle        = research.get("gsc") or {}

    candidates: list[dict] = []

    # ── Source 1: each seed keyword from the SERP snapshots ───────────────
    seen_keywords = set()
    for snap in (serps_bundle.get("snapshots") or []):
        kw = snap.get("keyword", "")
        if kw in seen_keywords:
            continue
        seen_keywords.add(kw)
        # Use US snapshot if available, else any market
        us_snap = next((s for s in serps_bundle["snapshots"]
                        if s["keyword"] == kw and s["market"] == "US"), snap)
        sub_scores = {
            "buyer_intent":           score_buyer_intent(kw),
            "product_fit":            score_product_fit(kw),
            "competitor_velocity":    score_competitor_velocity(competitors_bundle, kw),
            "keyword_demand":         50,  # would need DataForSEO volume — placeholder
            "serp_weakness":          score_serp_weakness(us_snap),
            "localization_potential": score_localization_potential(kw, serps_bundle),
            "internal_link_value":    score_internal_link_value(kw, inventory),
        }
        opp_score = _aggregate(sub_scores)
        match = find_matching_article(inventory, kw) if inventory else None
        candidates.append({
            "candidate_id":      f"serp-{kw}",
            "source":            "serp_snapshot",
            "keyword":           kw,
            "topic":             kw,
            "target_market":     "US",
            "recommended_action": "update_existing_article" if match else "create_new_article",
            "existing_article":  {"url": match["url"], "id": match["id"]} if match else None,
            "sub_scores":        sub_scores,
            "ai_overview_score": score_ai_overview(aio_bundle, kw),
            "opportunity_score": opp_score,
        })

    # ── Source 2: GSC striking-distance queries ───────────────────────────
    for r in (gsc_bundle.get("striking_distance_queries") or [])[:15]:
        kw = r["query"]
        if kw in seen_keywords:
            continue
        sub_scores = {
            "buyer_intent":           score_buyer_intent(kw),
            "product_fit":            score_product_fit(kw),
            "competitor_velocity":    score_competitor_velocity(competitors_bundle, kw),
            "keyword_demand":         min(100, 30 + int(r["impressions"] / 5)),
            "serp_weakness":          60,  # we're already ranking pos 8-25 — moderate weakness
            "localization_potential": 50,
            "internal_link_value":    70,  # we already have a page; just need to improve it
        }
        opp_score = _aggregate(sub_scores)
        candidates.append({
            "candidate_id":      f"gsc-strike-{kw}",
            "source":            "gsc_striking_distance",
            "keyword":           kw,
            "topic":             kw,
            "target_market":     "US",
            "recommended_action": "update_existing_article",
            "existing_article":  {"url": r["page"]},
            "current_position":  r["avg_position"],
            "current_impressions": r["impressions"],
            "sub_scores":        sub_scores,
            "ai_overview_score": 50,
            "opportunity_score": opp_score,
        })

    # Sort and persist
    candidates.sort(key=lambda c: c["opportunity_score"], reverse=True)

    result = {
        "date":             _dt.date.today().isoformat(),
        "candidates":       candidates,
        "total_candidates": len(candidates),
        "max_score":        candidates[0]["opportunity_score"] if candidates else 0,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"   ✓ Scored {len(candidates)} candidates (top: {result['max_score']})")
    return result


if __name__ == "__main__":
    # Standalone test — load latest research bundle + inventory from disk
    from research.runner import run_research_bundle
    from decision.content_inventory import build
    res = score(run_research_bundle(), build())
    print(json.dumps({
        "total": res["total_candidates"],
        "max":   res["max_score"],
        "top5":  [(c["keyword"], c["opportunity_score"], c["recommended_action"])
                  for c in res["candidates"][:5]],
    }, indent=2))
