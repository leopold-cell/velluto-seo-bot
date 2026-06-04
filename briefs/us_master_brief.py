"""
US master brief generator.

Hybrid approach (per Phase 4 plan):
  1. Mechanically build structural fields from research bundle (PAA questions,
     competitor titles, GSC queries, product-fit matrix).
  2. ONE Haiku call to enrich:
     - Velluto angle (main + supporting)
     - claims-to-avoid (specific to this topic)
     - competitor counter-angles
     - article tone notes

Output: brief dict matching spec line 1458-1542
Persisted to: output/us_master_brief_YYYY-MM-DD.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

import config_loader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(ROOT, ".env"), override=True)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
_client: Anthropic | None = None


def _client_lazy() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic()
    return _client


# ── Mechanical brief construction ─────────────────────────────────────────

def _gather_paa_questions(paa_bundle: dict, keyword: str, top_n: int = 6) -> list[dict]:
    """Extract the top high-intent PAA questions matching this keyword."""
    if not paa_bundle:
        return []
    matches = []
    for snap in (paa_bundle.get("extracted") or []):
        if snap.get("keyword", "").lower() == keyword.lower():
            matches.extend(snap.get("questions") or [])
    # Sort by buyer_intent_score desc, dedupe by question text
    seen = set()
    out = []
    for q in sorted(matches, key=lambda x: x.get("buyer_intent_score", 0), reverse=True):
        qtxt = q["question"].strip()
        if qtxt.lower() not in seen:
            seen.add(qtxt.lower())
            out.append(q)
        if len(out) >= top_n:
            break
    return out


def _gather_competitor_context(competitors_bundle: dict, keyword: str, top_n: int = 3) -> list[dict]:
    """Find competitor pages whose titles overlap this keyword."""
    if not competitors_bundle:
        return []
    kw_tokens = set(re.findall(r"\w+", keyword.lower()))
    hits = []
    for c in (competitors_bundle.get("new_topics_per_competitor") or []):
        for page in (c.get("page_intel") or []):
            title = (page.get("title") or "").lower()
            overlap = kw_tokens & set(re.findall(r"\w+", title))
            if len(overlap) >= 2:
                hits.append({
                    "competitor":     c.get("competitor"),
                    "observed_topic": page.get("title"),
                    "url":            page.get("url"),
                })
                if len(hits) >= top_n:
                    return hits
    return hits


def _match_problem_solution(keyword: str) -> dict | None:
    """
    Phase 4.5: if the keyword matches one of the problem→solution patterns in
    config/problem_solution_map.yml, return the matching entry (with USP +
    guarantee). Used by build_brief() to auto-inject the right value prop.
    """
    cfg = config_loader.get("problem_solution_map") or {}
    entries = cfg.get("problem_solution_map", []) or []
    kw = keyword.lower()
    for entry in entries:
        for pattern in entry.get("patterns", []):
            if pattern.lower() in kw:
                return entry
    return None


def _product_fit_angle(keyword: str) -> tuple[str, list[str]]:
    """Pick the strongest product_fit angle + supporting angles for this keyword."""
    pf = config_loader.velluto_positioning().get("product_fit", {})
    kw = keyword.lower()
    best_category, best_priority = None, 0
    supporting = []
    for category, data in pf.items():
        if any(k.lower() in kw for k in data.get("keywords", [])):
            if data.get("priority", 0) > best_priority:
                if best_category:
                    supporting.append(pf[best_category]["velluto_angle"])
                best_category = category
                best_priority = data["priority"]
            else:
                supporting.append(data["velluto_angle"])
    main_angle = pf[best_category]["velluto_angle"] if best_category else (
        "Premium road cycling glasses combining UV400, contrast, and Italian style."
    )
    return main_angle, supporting[:3]


def _build_internal_links(inventory: dict, keyword: str) -> list[dict]:
    """Pick 3-4 internal links from existing inventory + the mandatory homepage link."""
    links = [
        {"anchor": "Velluto", "url": "/"},  # MANDATORY (spec line 1620) — root-relative
        {"anchor": "Velluto Strada Pro", "url": "/collections/velluto-stradapro-cycling-glasses"},
        {"anchor": "cycling glasses collection", "url": "/collections/velluto-stradapro-cycling-glasses"},
    ]
    # Add 1-2 related articles from inventory
    kw_tokens = set(re.findall(r"\w+", keyword.lower()))
    related = []
    for a in (inventory.get("articles") or [])[:50]:
        title_tokens = set(re.findall(r"\w+", (a.get("title") or "").lower()))
        overlap = len(kw_tokens & title_tokens)
        if 1 <= overlap <= len(kw_tokens) - 1:  # related but not duplicate
            related.append({"anchor": a["title"], "url": a["url"]})
        if len(related) >= 2:
            break
    return links + related


def _content_type_for(keyword: str) -> str:
    kw = keyword.lower()
    if "vs" in kw or "alternative" in kw:           return "comparison"
    if "best " in kw:                                return "buying_guide"
    if "for " in kw or "fog" in kw or "wind" in kw: return "problem_solution"
    return "buying_guide"


# ── Haiku enrichment ──────────────────────────────────────────────────────

def _haiku_enrich(keyword: str, mechanical_brief: dict,
                  meta_ads_themes: str = "") -> dict:
    """ONE Haiku call to enrich with Velluto angle + claims-to-avoid + tone.

    Phase 4.5: extra context — if the topic matches a problem framing, we
    surface the guarantee. Optional meta_ads_themes line carries current
    paid-messaging vocabulary into the brief.
    """
    system = (
        "You are a brand strategist for Velluto (premium D2C road cycling eyewear).\n"
        "Brand voice: confident, performance-focused, Italian premium without overbranding.\n"
        "Slogan: 'Ride Fast. Live Slow.' Where performance meets la dolce vita.\n\n"
        "Return ONLY valid JSON, no markdown, no prose."
    )

    # Phase 4.5: problem-solution context block (when matched)
    problem_block = ""
    ps = mechanical_brief.get("problem_solution")
    if ps:
        problem_block = (
            f"\nProblem framing: this topic addresses a real cyclist pain point.\n"
            f"  Matched USP: {ps['matched_usp']}\n"
            f"  Guarantee:   {ps['guarantee_name']} — {ps['guarantee_text']}\n"
            f"  → Your CTA + tone must center the guarantee as the risk-reversal.\n"
        )

    # Phase 4.5: Meta Ads inspiration (when available)
    ads_block = ""
    if meta_ads_themes:
        ads_block = (
            f"\nCurrent paid-ad themes (alignment for organic tone):\n"
            f"  {meta_ads_themes}\n"
        )

    user = (
        f"Topic: {keyword}\n"
        f"Article type: {mechanical_brief['article_type']}\n"
        f"Existing product fit angle: {mechanical_brief['velluto_position']['main_angle']}\n"
        f"Competitor pages observed: {len(mechanical_brief['competitor_context'])}\n"
        f"{problem_block}{ads_block}\n"
        "Return JSON with these keys:\n"
        '{"target_reader": "<1 sentence describing the reader for this exact topic>", '
        '"reader_problem": "<1 sentence on the problem they face>", '
        '"sharpened_main_angle": "<1 sentence — sharpen the main angle for this topic, '
        "keep Velluto specific: UV400 / high-contrast lens / anti-fog / wind protection / "
        'helmet-fit / Italian style / premium-value-vs-Oakley>", '
        '"claims_to_avoid": ["<3-5 specific claims this article must NOT make, '
        'e.g. \'no photochromic claims\', \'no fake test data\', \'no \\"best for X\\" without criteria\'>"], '
        '"tone_notes": "<1 sentence — specific tone guidance>", '
        '"cta_text": "<5-10 word CTA line — if a guarantee was mentioned, weave it in>"}'
    )
    try:
        r = _client_lazy().messages.create(
            model=HAIKU_MODEL, max_tokens=600,
            system=system, messages=[{"role": "user", "content": user}],
        )
        raw = r.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"      ⚠️  Brief enrichment failed: {e} — using mechanical defaults")
        return {
            "target_reader":         "Road cyclist evaluating premium cycling glasses.",
            "reader_problem":        "Needs reliable eye protection and clear vision in changing conditions.",
            "sharpened_main_angle":  mechanical_brief["velluto_position"]["main_angle"],
            "claims_to_avoid": [
                "Do not claim photochromic lenses (Velluto does not offer them).",
                "Do not invent lab tests or certifications.",
                "Do not claim 'objectively best' without specific criteria.",
                "Do not hard-code prices — use the current commercial config.",
                "Do not link to competitor websites.",
            ],
            "tone_notes":  "Confident, clear, performance-led. Italian premium without overbranding.",
            "cta_text":    "Discover the Velluto Strada Pro.",
        }


# ── Main entrypoint ───────────────────────────────────────────────────────

def build_brief(decision: dict, research: dict, inventory: dict) -> dict:
    """
    Build the US master brief for the decision's chosen topic.

    Args:
      decision:   output of decision/topic_selector.choose()
      research:   output of research/runner.run_research_bundle()
      inventory:  output of decision/content_inventory.build()

    Returns the full brief dict (spec line 1458-1542 shape) ready to inject
    into the publish_de_primary path.
    """
    today = _dt.date.today().isoformat()
    keyword = decision["chosen_keyword"]

    main_angle, supporting_angles = _product_fit_angle(keyword)
    paa_questions = _gather_paa_questions(research.get("paa") or {}, keyword)
    competitor_context = _gather_competitor_context(research.get("competitors") or {}, keyword)
    internal_links = _build_internal_links(inventory, keyword)
    art_type = _content_type_for(keyword)

    # Phase 4.5: if the keyword is a problem framing, inject the matched USP + guarantee
    problem_match = _match_problem_solution(keyword)
    problem_solution_block = None
    if problem_match:
        # Promote the matched USP as the FIRST supporting angle
        supporting_angles = [problem_match["usp"]] + supporting_angles
        problem_solution_block = {
            "problem_id":     problem_match["id"],
            "matched_usp":    problem_match["usp"],
            "guarantee_name": problem_match["guarantee_name"],
            "guarantee_text": problem_match["guarantee_text"],
        }

    # Mechanical skeleton
    mechanical = {
        "brief_type":      "us_master_article",
        "date":            today,
        "topic":           keyword,
        "primary_keyword": keyword,
        "secondary_keywords": [],  # filled by Haiku-enriched section in Phase 5+
        "search_intent":   "commercial investigation",
        "buyer_intent_score": decision.get("sub_scores", {}).get("buyer_intent", 70),
        "opportunity_score":  decision.get("opportunity_score"),
        "article_type":    art_type,
        "velluto_position": {
            "main_angle": main_angle,
            "supporting_angles": supporting_angles,
        },
        "competitor_context": competitor_context,
        "must_answer_questions": [q["question"] for q in paa_questions],
        "paa_with_intent":       paa_questions,
        "required_sections": [
            "Short answer / TL;DR",
            "What matters in cycling sunglasses (criteria)",
            "Velluto positioning vs alternatives",
            "Real-world riding scenarios",
            "FAQ",
        ],
        "internal_links": internal_links,
        "commercial_config_required": True,
        "competitor_outbound_links_allowed": False,
        "target_market": "US",
        # Phase 4.5: present when keyword maps to a problem framing
        "problem_solution": problem_solution_block,
    }

    # Haiku enrichment — adds the Velluto-specific creative judgement.
    # Phase 4.5: surface current Meta-ad themes so organic tone aligns with paid messaging.
    meta_ads_themes = ((research.get("meta_ads") or {}).get("themes_summary") or "")
    enrich = _haiku_enrich(keyword, mechanical, meta_ads_themes=meta_ads_themes)
    mechanical.update({
        "target_reader":   enrich.get("target_reader"),
        "reader_problem": enrich.get("reader_problem"),
        "tone":            enrich.get("tone_notes", "confident, premium, performance-focused"),
        "cta":             enrich.get("cta_text", "Discover the Velluto Strada Pro."),
        "do_not_claim":    enrich.get("claims_to_avoid", []),
    })
    # Sharpened angle replaces main_angle if provided
    if enrich.get("sharpened_main_angle"):
        mechanical["velluto_position"]["main_angle"] = enrich["sharpened_main_angle"]

    # Persist
    path = os.path.join(ROOT, "output", f"us_master_brief_{today}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mechanical, f, indent=2, ensure_ascii=False)
    print(f"   ✓ Master brief built: {len(mechanical['must_answer_questions'])} PAA, "
          f"{len(competitor_context)} competitor refs, "
          f"{len(mechanical['internal_links'])} internal links")
    return mechanical


if __name__ == "__main__":
    fake_decision = {
        "chosen_keyword": "best cycling sunglasses",
        "chosen_action":  "create_new_article",
        "opportunity_score": 75,
        "sub_scores": {"buyer_intent": 90, "product_fit": 90},
    }
    fake_research = {"paa": {}, "competitors": {}, "ai_overviews": {}}
    fake_inventory = {"articles": []}
    b = build_brief(fake_decision, fake_research, fake_inventory)
    print(json.dumps(b, indent=2, ensure_ascii=False))
