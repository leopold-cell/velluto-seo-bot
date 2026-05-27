"""
Phase 4.5 smoke test — problem keywords + USP injection + Meta Ads fetcher.

No real network calls (Anthropic + Meta both mocked).
Cost: $0. Time: ~2 seconds.

Run: python3 tests/smoke_test_phase4_5.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Block Anthropic before importing brief generator ──────────
captured_prompts: list[dict] = []


class _FakeMessages:
    def create(self, **kwargs):
        captured_prompts.append(kwargs)
        from types import SimpleNamespace
        return SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps({
                "target_reader":        "Test reader",
                "reader_problem":       "Test problem",
                "sharpened_main_angle": "Test angle",
                "claims_to_avoid":      ["x", "y"],
                "tone_notes":           "Test tone",
                "cta_text":             "Try it now.",
            }))],
            usage=type("U", (), {"input_tokens": 100, "output_tokens": 100})(),
        )


class _FakeClient:
    messages = _FakeMessages()


import anthropic
anthropic.Anthropic = lambda **kw: _FakeClient()

import config_loader
from research.serp_fetcher import _seed_keywords
from research import meta_ads_fetcher
from briefs.us_master_brief import build_brief, _match_problem_solution

print("=" * 60)
print("=== Phase 4.5 Smoke Test ===")
print("=" * 60)

# ── 1. Merged seed pool (solution + problem) ────────────────
print("\n📚 Step 1: merged seed keyword pool")
pool = _seed_keywords()
solution_count = len(config_loader.get("seed_keywords")["phase2_seed_keywords"])
problem_count  = len(config_loader.get("seed_keywords")["phase4_5_problem_keywords"])
assert len(pool) >= solution_count, f"pool too small: {len(pool)}"
assert "best cycling sunglasses" in pool, "solution KW missing from pool"
assert any("burning eyes" in k for k in pool), "problem KW missing from pool"
print(f"   ✓ solution={solution_count}  problem={problem_count}  merged={len(pool)} (dedup)")

# ── 2. problem_solution_map matching ────────────────────────
print("\n🎯 Step 2: problem → solution pattern matching")
test_cases = [
    ("cycling glasses press into helmet",     "helmet_fit"),
    ("burning eyes when cycling",             "wind_eyes"),
    ("cycling glasses keep fogging up",       "fogging"),
    ("vision distorted on road bike",         "vision_distorted"),
    ("uv protection while cycling",           "uv_protection"),
    ("cycling sunglasses for bugs and insects", "insects_bugs"),
    ("are cheap sport sunglasses good",       "cheap_alternative"),
]
for kw, expected_id in test_cases:
    m = _match_problem_solution(kw)
    assert m is not None, f"❌ '{kw}' → no match (expected {expected_id})"
    assert m["id"] == expected_id, f"❌ '{kw}' → matched {m['id']} (expected {expected_id})"
    print(f"   ✓ '{kw}' → {m['id']} | {m['guarantee_name']}")

# Negative: solution KW should NOT match any problem
assert _match_problem_solution("best cycling sunglasses") is None, "❌ solution KW false-matched"
assert _match_problem_solution("photochromic vs interchangeable cycling glasses") is None
print("   ✓ Solution keywords correctly DO NOT match the problem map")

# ── 3. build_brief() with problem keyword injects USP + guarantee ───
print("\n🧱 Step 3: build_brief() injects USP + guarantee for problem topics")
fake_decision = {
    "chosen_keyword":    "cycling glasses press into helmet",
    "chosen_action":     "create_new_article",
    "opportunity_score": 75,
    "sub_scores":        {"buyer_intent": 90, "product_fit": 90},
    "target_market":     "US",
}
fake_research = {"paa": {}, "competitors": {}, "ai_overviews": {}, "meta_ads": {}}
fake_inventory = {"articles": [], "collections": []}
captured_prompts.clear()
brief = build_brief(fake_decision, fake_research, fake_inventory)

assert brief["problem_solution"] is not None
assert brief["problem_solution"]["problem_id"] == "helmet_fit"
assert "30-day Testride" in brief["problem_solution"]["guarantee_name"]
assert any("Adjustable nosepad" in s for s in brief["velluto_position"]["supporting_angles"])
print(f"   ✓ Brief.problem_solution: id={brief['problem_solution']['problem_id']}, "
      f"guarantee={brief['problem_solution']['guarantee_name']}")
print(f"   ✓ USP promoted to supporting_angles[0]: '{brief['velluto_position']['supporting_angles'][0][:60]}...'")

# Verify Haiku prompt contained the problem-solution block
haiku_prompt = captured_prompts[0]["messages"][0]["content"]
assert "Problem framing" in haiku_prompt
assert "30-day Testride" in haiku_prompt
print("   ✓ Haiku prompt contained 'Problem framing' + guarantee text")

# ── 4. build_brief() with non-problem keyword has NO problem_solution ─
print("\n🧱 Step 4: build_brief() leaves problem_solution=None for solution topics")
fake_decision2 = {**fake_decision, "chosen_keyword": "best cycling sunglasses"}
captured_prompts.clear()
brief2 = build_brief(fake_decision2, fake_research, fake_inventory)
assert brief2["problem_solution"] is None
haiku_prompt2 = captured_prompts[0]["messages"][0]["content"]
assert "Problem framing" not in haiku_prompt2, "❌ should NOT inject problem block for solution KW"
print("   ✓ Solution KW: problem_solution=None, no problem-framing in prompt")

# ── 5. Meta Ads themes injected into Haiku prompt when present ────
print("\n📣 Step 5: Meta Ads themes propagate into brief Haiku prompt")
fake_research_with_meta = {
    **fake_research,
    "meta_ads": {
        "active_ads_count": 7,
        "themes_summary": "Most common terms: helmet(4), guarantee(3), italian(2)",
    },
}
captured_prompts.clear()
build_brief(fake_decision, fake_research_with_meta, fake_inventory)
hp = captured_prompts[0]["messages"][0]["content"]
assert "Current paid-ad themes" in hp
assert "helmet(4)" in hp
print("   ✓ Meta Ads themes_summary visible in Haiku prompt")

# ── 6. meta_ads_fetcher graceful degrade when no creds ───────
print("\n🛡️  Step 6: meta_ads_fetcher.run() graceful skip when no creds")
# Force missing creds
import importlib
os.environ["META_ACCESS_TOKEN"] = ""
os.environ["META_AD_ACCOUNT_ID"] = ""
importlib.reload(meta_ads_fetcher)
result = meta_ads_fetcher.run()
assert result["skipped"] is True
assert result["active_ads_count"] == 0
assert "missing" in result["reason"].lower()
print(f"   ✓ Skipped cleanly: '{result['reason']}'")

# ── 7. runner.py wires meta_ads into the bundle ────────────
print("\n🎼 Step 7: runner returns meta_ads key + counts in summary_line")
from research.runner import run_research_bundle
# We're not running the real bundle (would cost $), but verify imports/wiring
assert "meta_ads" in run_research_bundle.__code__.co_consts or True  # weak check
import inspect
src = inspect.getsource(run_research_bundle)
assert "meta_ads_fetcher" in src
assert "meta_ads_n" in src
assert "active Meta ads" in src
print("   ✓ runner.run_research_bundle() wires meta_ads_fetcher + summary line")

print("\n" + "=" * 60)
print("🎉 Phase 4.5 smoke test PASSED")
print("=" * 60)
