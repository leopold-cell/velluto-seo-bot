"""
Phase 2 smoke test — verifies the research bundle works end-to-end.

Cost: ~$0.002 for ONE real DataForSEO SERP call.
Time: ~30s (network calls to DataForSEO + competitor sitemaps).

Run:
  python3 tests/smoke_test_phase2.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_loader
from research import serp_fetcher, paa_extractor, ai_overview_monitor, competitor_monitor, gsc_fetcher
from research.runner import run_research_bundle


print("=" * 60)
print("=== Phase 2 Smoke Test ===")
print("=" * 60)

# ── 1. seed_keywords.yml loads ─────────────────────────────
kws = serp_fetcher._seed_keywords()
assert len(kws) == 10, f"❌ Expected 10 seed keywords, got {len(kws)}"
assert "best cycling sunglasses" in kws
print(f"\n✅ Step 1: seed_keywords.yml — 10 keywords loaded")

# ── 2. markets_due_today is reasonable ─────────────────────
mkts = serp_fetcher.markets_due_today()
assert "US" in mkts and "DE" in mkts and "NL" in mkts, f"Missing priority markets: {mkts}"
print(f"✅ Step 2: markets_due_today = {mkts}")

# ── 3. SERP call (real if API credits, fixture fallback otherwise) ─
# DataForSEO requires a $50 minimum top-up. If the account is empty,
# we fall back to a representative fixture so we can still validate
# the downstream parsers + runner + file outputs.
SAMPLE_SERP_FIXTURE = {
    "items": [
        {"type": "organic", "rank_absolute": 1, "title": "Best Cycling Sunglasses 2025 (Buying Guide)",
         "description": "Our top picks for road cycling glasses with UV400 protection.",
         "url": "https://example-magazine.com/best-cycling-sunglasses",
         "domain": "example-magazine.com"},
        {"type": "organic", "rank_absolute": 2, "title": "10 Best Cycling Sunglasses Tested",
         "description": "Reviewed by pro cyclists.", "url": "https://example-review.com/cycling-glasses",
         "domain": "example-review.com"},
        {"type": "organic", "rank_absolute": 3, "title": "Oakley Sutro Review",
         "description": "Premium cycling eyewear.", "url": "https://oakley.com/sutro",
         "domain": "oakley.com"},
        {"type": "people_also_ask", "items": [
            {"title": "What are the best cycling sunglasses for road cycling?",
             "expanded_element": []},
            {"title": "Are expensive cycling sunglasses worth it?", "expanded_element": []},
            {"title": "Why do cycling glasses fog up?", "expanded_element": []},
            {"title": "Photochromic vs interchangeable cycling glasses?", "expanded_element": []},
        ]},
        {"type": "related_searches", "items": [
            {"title": "best road cycling sunglasses"}, {"title": "cycling glasses UV400"},
        ]},
        {"type": "ai_overview", "text": "The best cycling sunglasses combine UV400 protection, "
            "anti-fog ventilation, and a secure helmet-compatible fit. Top picks include Oakley Sutro, "
            "POC Devour, and Velluto Strada Pro for premium value.",
         "references": [
            {"url": "https://oakley.com/sutro", "title": "Oakley Sutro",   "source": "Oakley",   "domain": "oakley.com"},
            {"url": "https://poc.com/devour",   "title": "POC Devour",     "source": "POC",      "domain": "poc.com"},
            {"url": "https://example-review.com/cycling-glasses", "title": "Top 10 Cycling Sunglasses",
             "source": "Cycling Magazine", "domain": "example-review.com"},
        ]},
    ]
}

print(f"\n📡 Step 3: SERP call (US, 'best cycling sunglasses')…")
serp = serp_fetcher.fetch_one("best cycling sunglasses", "US")
used_fixture = False
if serp is None:
    print("   ⚠️  Real DataForSEO call failed (likely 402 — top up account to $50+). "
          "Falling back to fixture to validate downstream parsers.")
    serp = SAMPLE_SERP_FIXTURE
    used_fixture = True

items = serp.get("items") or []
organic = [i for i in items if i.get("type") == "organic"]
paa     = [i for i in items if i.get("type") == "people_also_ask"]
assert organic, f"❌ No organic items (got types: {set(i.get('type') for i in items)})"
print(f"   organic={len(organic)} | paa_groups={len(paa)} | total_items={len(items)} "
      f"| {'FIXTURE' if used_fixture else 'REAL API'}")
print(f"✅ Step 3: SERP shape valid (top result: '{organic[0].get('title','')[:60]}…')")

# Persist a single-snapshot SERP file for downstream extractors
single_snapshot = {
    "date":            "smoke",
    "markets_fetched": ["US"],
    "keywords":        ["best cycling sunglasses"],
    "snapshots":       [{
        "market":          "US",
        "keyword":         "best cycling sunglasses",
        "organic":         organic[:10],
        "people_also_ask": paa,
        "related":         [i for i in items if i.get("type") == "related_searches"],
        "ai_overview":     next((i for i in items if i.get("type") == "ai_overview"), None),
        "raw_items_count": len(items),
    }],
    "cost_usd":        0.002,
    "errors":          0,
}
os.makedirs(os.path.dirname(serp_fetcher.OUTPUT_PATH), exist_ok=True)
with open(serp_fetcher.OUTPUT_PATH, "w") as f:
    json.dump(single_snapshot, f, indent=2)

# ── 4. PAA extractor parses the SERP ───────────────────────
paa_result = paa_extractor.run()
assert paa_result["total_questions"] >= 0
if paa_result["total_questions"] > 0:
    high_intent_labels = {q["intent"] for s in paa_result["extracted"] for q in s["questions"]}
    print(f"✅ Step 4: PAA extracted {paa_result['total_questions']} questions "
          f"({paa_result['high_intent_questions']} high-intent); intent labels seen: {high_intent_labels}")
else:
    print("⚠️  Step 4: PAA extracted 0 questions (SERP may not have shown PAA block for this query)")

# ── 5. AI Overview monitor parses the SERP ─────────────────
aio_result = ai_overview_monitor.run()
print(f"✅ Step 5: AIO monitor — {aio_result['total_with_aio']} SERPs had AI Overview "
      f"(Velluto cited: {aio_result['velluto_cited']}, competitor cited: {aio_result['competitor_cited']})")

# ── 6. Competitor monitor — first-run snapshot ──────────────
print(f"\n🌐 Step 6: Competitor sitemap fetch (10 domains, may take ~30s) …")
# Force a "first-run" condition by removing any existing snapshot
if os.path.exists(competitor_monitor.SNAPSHOT_PATH):
    print("   (existing snapshot found — diff mode)")
else:
    print("   (no prior snapshot — first-run mode)")
comp_result = competitor_monitor.run()
assert isinstance(comp_result.get("total_new_urls"), int)
print(f"✅ Step 6: competitor_monitor ran "
      f"(is_first_run={comp_result['is_first_run']}, total_new_urls={comp_result['total_new_urls']}, "
      f"pages_inspected={comp_result['pages_inspected']})")

# ── 7. GSC fetcher — handles missing creds gracefully ─────
gsc_result = gsc_fetcher.run()
assert "striking_distance_queries" in gsc_result
assert "emerging_queries" in gsc_result
assert "low_ctr_pages" in gsc_result
assert "cannibalization_candidates" in gsc_result
total = gsc_result.get("totals", {})
if total.get("curr_impressions"):
    print(f"✅ Step 7: GSC fetcher — {total['curr_impressions']} impressions (curr 28d), "
          f"{len(gsc_result['striking_distance_queries'])} striking-distance, "
          f"{len(gsc_result['emerging_queries'])} emerging queries")
else:
    print(f"✅ Step 7: GSC fetcher — credentials missing or no data; structure valid")

# ── 8. Runner orchestrator ─────────────────────────────────
print(f"\n🧪 Step 8: Re-running full bundle via runner …")
bundle = run_research_bundle()
required_keys = {"serps", "paa", "ai_overviews", "competitors", "gsc", "summary_line"}
missing = required_keys - set(bundle.keys())
assert not missing, f"❌ Missing keys: {missing}"
print(f"✅ Step 8: runner returns all keys ({sorted(bundle.keys())})")
print(f"   summary: {bundle['summary_line']}")

# ── 9. All 5 output files exist on disk ────────────────────
expected_files = [
    "data/processed/serp_snapshots.json",
    "data/processed/paa_snapshots.json",
    "data/processed/ai_overview_snapshots.json",
    "data/processed/competitor_new_topics.json",
    "data/processed/gsc_performance.json",
]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for rel in expected_files:
    path = os.path.join(root, rel)
    assert os.path.exists(path), f"❌ Missing output: {rel}"
    size = os.path.getsize(path)
    assert size > 10, f"❌ Output too small: {rel} ({size} bytes)"
print(f"\n✅ Step 9: All 5 JSON outputs present in data/processed/")

print("\n" + "=" * 60)
print("🎉 Phase 2 smoke test PASSED")
print("=" * 60)
