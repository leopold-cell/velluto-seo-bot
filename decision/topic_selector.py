"""
Daily Topic Selector — Claude Haiku picks ONE action from the 10 options.

Inputs:
  - scored opportunities (from opportunity_scorer.score)
  - research bundle (Phase 2)
  - content inventory

Returns the chosen action + topic + reasoning per spec line 1907-1945.

Gates (from config/publishing_rules.yml):
  - create_new_article         requires opportunity_score >= 72, buyer_intent >= 65, product_fit >= 70
  - update_existing_article    requires opportunity_score >= 55
  - else → monitor_only / add_internal_links / rewrite_metadata

Output: output/chosen_action.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

import config_loader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(ROOT, ".env"), override=True)

OUTPUT_PATH = os.path.join(ROOT, "output", "chosen_action.json")
HAIKU_MODEL = "claude-haiku-4-5-20251001"

_client: Anthropic | None = None


def _client_lazy() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic()
    return _client


def _gate(candidate: dict, rules: dict) -> str | None:
    """Return the highest-tier action this candidate qualifies for, or None to skip."""
    sub = candidate["sub_scores"]
    opp = candidate["opportunity_score"]
    nar = rules["publishing_rules"]["new_article"]
    upd = rules["publishing_rules"]["update_existing_article"]

    is_update_candidate = candidate.get("recommended_action") == "update_existing_article"

    if (not is_update_candidate
        and opp >= nar["min_opportunity_score"]
        and sub["buyer_intent"] >= nar["min_buyer_intent_score"]
        and sub["product_fit"]  >= nar["min_product_fit_score"]):
        return "create_new_article"

    if opp >= upd["min_opportunity_score"]:
        return "update_existing_article"

    if opp < rules["publishing_rules"]["ignore"]["if_buyer_intent_below"]:
        return None

    return "monitor_only"


def _build_candidate_summary(candidates: list[dict], rules: dict) -> str:
    lines = []
    for i, c in enumerate(candidates[:15]):
        gated = _gate(c, rules)
        if gated is None:
            continue
        lines.append(
            f"  #{i+1}  score={c['opportunity_score']}  "
            f"action={gated}  kw='{c['keyword']}' "
            f"(buyer={c['sub_scores']['buyer_intent']}, "
            f"fit={c['sub_scores']['product_fit']}, "
            f"serp_weak={c['sub_scores']['serp_weakness']}, "
            f"aio={c.get('ai_overview_score','-')})"
        )
        if c.get("existing_article"):
            lines.append(f"        existing: {c['existing_article'].get('url','')}")
    return "\n".join(lines) if lines else "  (no candidates met any threshold)"


def choose(scored: dict, research: dict, inventory: dict) -> dict:
    """
    Pick ONE action. Returns:
      {
        date, chosen_action, chosen_topic, chosen_keyword, target_market,
        existing_article_url, opportunity_score, why_this_topic,
        why_not_the_others, required_content_type, risk_notes, fallback
      }
    """
    today = _dt.date.today().isoformat()
    rules = config_loader.publishing_rules()
    candidates = scored.get("candidates") or []

    # ── Hard fallback if no candidates at all ─────────────────────────────
    if not candidates:
        out = {
            "date": today, "chosen_action": "monitor_only",
            "chosen_topic": None, "chosen_keyword": None,
            "target_market": "US", "opportunity_score": 0,
            "why_this_topic": "No candidate opportunities scored above threshold today.",
            "fallback": True,
        }
        _save(out)
        return out

    # ── Pre-gate candidates ────────────────────────────────────────────────
    # Filter to ones that pass at least monitor_only gate (i.e. above the ignore threshold)
    gated_candidates = [(c, _gate(c, rules)) for c in candidates]
    gated_candidates = [(c, a) for c, a in gated_candidates if a is not None]

    actionable = [(c, a) for c, a in gated_candidates if a != "monitor_only"]

    if not actionable:
        # Everything is monitor_only — pick the highest-scoring one for logging
        top = gated_candidates[0][0] if gated_candidates else candidates[0]
        out = {
            "date": today,
            "chosen_action":      "monitor_only",
            "chosen_topic":       top["keyword"],
            "chosen_keyword":     top["keyword"],
            "target_market":      top.get("target_market", "US"),
            "opportunity_score":  top["opportunity_score"],
            "why_this_topic":     f"No candidate met the create/update thresholds today "
                                  f"(top score {top['opportunity_score']}, "
                                  f"requires {rules['publishing_rules']['update_existing_article']['min_opportunity_score']} to update).",
            "fallback":           False,
        }
        _save(out)
        return out

    # ── Ask Haiku to pick from the top 10 actionable candidates ───────────
    top_summary = _build_candidate_summary([c for c, _ in actionable], rules)
    system = (
        "You are the daily SEO/GEO topic selector for Velluto (premium D2C cycling eyewear).\n\n"
        "Your job: choose the SINGLE highest-value SEO/GEO action for today.\n\n"
        "Possible actions: create_new_article, update_existing_article, monitor_only.\n\n"
        "Decision criteria:\n"
        "- High purchase intent beats high search volume\n"
        "- Velluto product fit is mandatory (UV400, contrast, anti-fog, wind, helmet-fit, premium-value, style)\n"
        "- Prefer BOFU/MOFU over TOFU\n"
        "- Avoid cannibalization with existing pages\n"
        "- If no strong opportunity, choose monitor_only\n\n"
        "Return ONLY valid JSON. No prose. No code fences."
    )
    user = (
        f"Today's research summary: {research.get('summary_line', 'n/a')}\n\n"
        f"Top candidates (pre-gated):\n{top_summary}\n\n"
        f"Existing Velluto inventory: {inventory.get('total_articles', 0)} articles, "
        f"{inventory.get('total_collections', 0)} collections.\n\n"
        "Pick ONE candidate. Return JSON:\n"
        '{"chosen_candidate_index": <int>, "chosen_action": "create_new_article|update_existing_article|monitor_only", '
        '"why_this_topic": "<1 sentence>", "why_not_the_others": "<1 sentence>", '
        '"required_content_type": "buying_guide|comparison|problem_solution|alternative_page|update_existing", '
        '"risk_notes": "<1 short sentence>"}'
    )
    try:
        r = _client_lazy().messages.create(
            model=HAIKU_MODEL, max_tokens=400,
            system=system, messages=[{"role": "user", "content": user}],
        )
        raw = r.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        parsed = json.loads(raw)
        idx   = parsed.get("chosen_candidate_index", 0)
        idx   = max(0, min(idx - 1, len(actionable) - 1))  # tolerate 1-indexed
        chosen_candidate, gated_action = actionable[idx]
        chosen_action = parsed.get("chosen_action") or gated_action
        # Safety: never escalate past what the gate allowed
        if chosen_action == "create_new_article" and gated_action != "create_new_article":
            chosen_action = gated_action
    except Exception as e:
        print(f"   ⚠️  Topic selector Haiku call failed: {e} — using top-gated candidate")
        chosen_candidate, chosen_action = actionable[0]
        parsed = {
            "why_this_topic": "Auto-picked highest-scoring gated candidate (LLM call failed).",
            "why_not_the_others": "",
            "required_content_type": "buying_guide",
            "risk_notes": "",
        }

    out = {
        "date":                 today,
        "chosen_action":        chosen_action,
        "chosen_topic":         chosen_candidate["keyword"],
        "chosen_keyword":       chosen_candidate["keyword"],
        "target_market":        chosen_candidate.get("target_market", "US"),
        "opportunity_score":    chosen_candidate["opportunity_score"],
        "sub_scores":           chosen_candidate["sub_scores"],
        "existing_article_url": (chosen_candidate.get("existing_article") or {}).get("url"),
        "source":               chosen_candidate.get("source"),
        "why_this_topic":       parsed.get("why_this_topic", ""),
        "why_not_the_others":   parsed.get("why_not_the_others", ""),
        "required_content_type": parsed.get("required_content_type", "buying_guide"),
        "risk_notes":           parsed.get("risk_notes", ""),
        "fallback":             False,
    }
    _save(out)
    return out


def _save(payload: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ── Daily Research Report (spec line 1402-1450) ───────────────────────────

def write_daily_research_report(decision: dict, scored: dict, research: dict) -> None:
    """Persist a one-line-per-day strategic decision log to output/daily_research_report.json."""
    today = _dt.date.today().isoformat()
    path = os.path.join(ROOT, "output", "daily_research_report.json")
    history: list = []
    if os.path.exists(path):
        try:
            history = json.load(open(path))
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []

    competitors = (research.get("competitors") or {})
    gsc         = (research.get("gsc") or {})
    aio         = (research.get("ai_overviews") or {})

    history.append({
        "date":                       today,
        "summary": {
            "new_competitor_pages_found":   competitors.get("total_new_urls", 0),
            "candidates_scored":            scored.get("total_candidates", 0),
            "max_opportunity_score":        scored.get("max_score", 0),
            "ai_overview_opportunities":    aio.get("total_with_aio", 0),
            "gsc_striking_distance_count":  len(gsc.get("striking_distance_queries") or []),
            "chosen_action":                decision.get("chosen_action"),
        },
        "top_opportunities": [
            {"topic": c["keyword"], "opportunity_score": c["opportunity_score"],
             "recommended_action": c["recommended_action"]}
            for c in (scored.get("candidates") or [])[:5]
        ],
        "chosen_topic": {
            "topic":              decision.get("chosen_topic"),
            "keyword":            decision.get("chosen_keyword"),
            "action":             decision.get("chosen_action"),
            "score":              decision.get("opportunity_score"),
            "why_this_topic":     decision.get("why_this_topic"),
        },
    })
    # Keep last 365 days
    history = history[-365:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    from research.runner import run_research_bundle
    from decision.content_inventory import build
    from decision.opportunity_scorer import score
    r = run_research_bundle()
    inv = build()
    sc = score(r, inv)
    d = choose(sc, r, inv)
    print(json.dumps(d, indent=2, ensure_ascii=False))
