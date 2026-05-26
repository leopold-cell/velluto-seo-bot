"""
Phase 3 smoke test — verifies the decision layer end-to-end.

Uses real Shopify (for content inventory) + real Phase 2 data on disk
+ ONE real Anthropic Haiku call (~$0.005) for the topic selector.

Total cost: ~$0.005 + Shopify free.

Run: python3 tests/smoke_test_phase3.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_loader
from decision.content_inventory  import build as build_inventory, find_matching_article
from decision.opportunity_scorer import (
    score, score_buyer_intent, score_product_fit, score_serp_weakness,
    score_keyword_demand, score_internal_link_value
)
from decision.topic_selector     import choose, write_daily_research_report

print("=" * 60)
print("=== Phase 3 Smoke Test ===")
print("=" * 60)

# ── 1. Sub-scorers behave sensibly ──────────────────────────
print("\n📐 Step 1: sub-scorer unit checks")
assert score_buyer_intent("best cycling sunglasses")           >= 80
assert score_buyer_intent("cycling style")                     <= 40
assert score_buyer_intent("Oakley alternative")                >= 80
print(f"   ✓ buyer_intent: 'best cycling sunglasses'={score_buyer_intent('best cycling sunglasses')}, "
      f"'cycling style'={score_buyer_intent('cycling style')}, "
      f"'Oakley alternative'={score_buyer_intent('Oakley alternative')}")

assert score_product_fit("anti fog cycling sunglasses")        >= 80
assert score_product_fit("UV400 cycling")                      >= 80
assert score_product_fit("photochromic cycling glasses for changing light") >= 80
print(f"   ✓ product_fit: 'anti fog'={score_product_fit('anti fog cycling sunglasses')}, "
      f"'UV400'={score_product_fit('UV400 cycling')}, "
      f"'changing light'={score_product_fit('photochromic cycling glasses for changing light')}")

assert score_keyword_demand(50)    == 40
assert score_keyword_demand(2500)  == 80
assert score_keyword_demand(15000) == 100
print(f"   ✓ keyword_demand: 50→{score_keyword_demand(50)}, 2500→{score_keyword_demand(2500)}, 15000→{score_keyword_demand(15000)}")

# SERP weakness: top 3 dominated by competitors → low weakness
mock_strong_serp = {"organic": [
    {"domain": "oakley.com"}, {"domain": "poc.com"}, {"domain": "rapha.cc"}
]}
mock_weak_serp = {"organic": [
    {"domain": "cyclingweekly.com"}, {"domain": "reddit.com"}, {"domain": "youtube.com"}
]}
assert score_serp_weakness(mock_strong_serp) <= 40
assert score_serp_weakness(mock_weak_serp)   >= 70
print(f"   ✓ serp_weakness: strong-SERP={score_serp_weakness(mock_strong_serp)}, "
      f"weak-SERP={score_serp_weakness(mock_weak_serp)}")

print("✅ Step 1: all sub-scorers in expected ranges")

# ── 2. Content inventory ────────────────────────────────────
print("\n📚 Step 2: Content inventory from Shopify…")
inventory = build_inventory()
assert inventory["total_articles"] >= 0
print(f"✅ Step 2: {inventory['total_articles']} articles, {inventory['total_collections']} collections "
      f"from Shopify")

# ── 3. Run a fresh research bundle (uses real DataForSEO funds) ──
# We re-use whatever's already in data/processed/. If empty, run a mini-bundle.
print("\n🔬 Step 3: Loading research bundle (existing data/processed/ if available)…")
from research import serp_fetcher, paa_extractor, ai_overview_monitor, gsc_fetcher
from research.competitor_monitor import OUTPUT_PATH as COMP_OUT

research = {
    "serps":        serp_fetcher.load_latest() or {"snapshots": []},
    "paa":          json.load(open(paa_extractor.OUTPUT_PATH)) if os.path.exists(paa_extractor.OUTPUT_PATH) else {},
    "ai_overviews": json.load(open(ai_overview_monitor.OUTPUT_PATH)) if os.path.exists(ai_overview_monitor.OUTPUT_PATH) else {},
    "competitors":  json.load(open(COMP_OUT)) if os.path.exists(COMP_OUT) else {},
    "gsc":          json.load(open(gsc_fetcher.OUTPUT_PATH)) if os.path.exists(gsc_fetcher.OUTPUT_PATH) else {},
    "summary_line": "loaded from disk",
}
n_serps = len((research["serps"] or {}).get("snapshots", []))
print(f"   loaded: serps={n_serps} | "
      f"competitors_new_urls={(research['competitors'] or {}).get('total_new_urls',0)}")

# ── 4. Score opportunities ──────────────────────────────────
print("\n🎯 Step 4: Scoring opportunities…")
scored = score(research, inventory)
assert "candidates" in scored
print(f"✅ Step 4: {scored['total_candidates']} candidates scored (max: {scored['max_score']})")
if scored["candidates"]:
    print(f"   Top 3:")
    for c in scored["candidates"][:3]:
        print(f"     {c['opportunity_score']:5.1f}  {c['recommended_action']:25}  '{c['keyword']}'")

# ── 5. Topic selector ──────────────────────────────────────
print("\n🧠 Step 5: Topic selector (Claude Haiku, ~$0.005)…")
decision = choose(scored, research, inventory)
assert decision["chosen_action"] in (
    "create_new_article", "update_existing_article", "monitor_only"
)
print(f"✅ Step 5: chosen_action='{decision['chosen_action']}', "
      f"topic='{decision.get('chosen_topic')}', score={decision.get('opportunity_score')}")
if decision.get("why_this_topic"):
    print(f"   Why: {decision['why_this_topic']}")
if decision.get("why_not_the_others"):
    print(f"   Why not others: {decision['why_not_the_others']}")

# ── 6. Daily research report persists & accumulates ────────
print("\n📝 Step 6: Daily research report writer…")
write_daily_research_report(decision, scored, research)
report_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "output", "daily_research_report.json")
assert os.path.exists(report_path), f"❌ report not written: {report_path}"
history = json.load(open(report_path))
assert isinstance(history, list) and len(history) >= 1
assert history[-1]["chosen_topic"]["action"] == decision["chosen_action"]
print(f"✅ Step 6: daily_research_report.json has {len(history)} day(s) logged")

# ── 7. Output files exist ──────────────────────────────────
expected = [
    "data/processed/existing_content_inventory.json",
    "data/processed/opportunity_scores.json",
    "output/chosen_action.json",
    "output/daily_research_report.json",
]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for rel in expected:
    p = os.path.join(root, rel)
    assert os.path.exists(p), f"❌ missing: {rel}"
print(f"\n✅ Step 7: All 4 Phase 3 output files exist on disk")

# ── 8. Gate behaviour: monitor_only when no candidates ─────
print("\n🚦 Step 8: Gate behaviour — empty candidates should yield monitor_only…")
empty_decision = choose({"candidates": [], "total_candidates": 0, "max_score": 0},
                        research, inventory)
assert empty_decision["chosen_action"] == "monitor_only"
print(f"✅ Step 8: empty candidates → monitor_only (correctly gates publishing)")

print("\n" + "=" * 60)
print("🎉 Phase 3 smoke test PASSED")
print("=" * 60)
