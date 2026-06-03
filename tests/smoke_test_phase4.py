"""
Phase 4 smoke test — verifies brief building + quality gate end-to-end.

Cost: ~$0.01 (one Haiku call to enrich the master brief).
Time: ~10s (mostly Shopify inventory fetch).

Run: python3 tests/smoke_test_phase4.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Block Anthropic + Shopify network in seo_bot to verify brief flows into prompt ─
captured_prompts: list[dict] = []


class _FakeMessages:
    def create(self, **kwargs):
        captured_prompts.append(kwargs)
        from types import SimpleNamespace
        return SimpleNamespace(
            content=[SimpleNamespace(text=(
                '===TITLE===\nBest Cycling Sunglasses Test\n'
                '===META===\nBest cycling sunglasses with UV400 and anti-fog.\n'
                '===BODY===\n<h1>Best Cycling Sunglasses</h1>'
                + '<p>Lorem ipsum about cycling glasses and UV400 protection. ' + 'lorem ' * 700 + '</p>'
                + '<h2>What are the best cycling sunglasses?</h2><p>UV400.</p>'
            ))],
            usage=type("U", (), {"input_tokens": 100, "output_tokens": 100})(),
        )


class _FakeClient:
    messages = _FakeMessages()


print("=" * 60)
print("=== Phase 4 Smoke Test ===")
print("=" * 60)

# ── 1. Quality gate offline behaviour ─────────────────────────
print("\n🔍 Step 1: Quality gate offline checks")
from briefs.quality_gate import gate, strip_competitor_links, ensure_homepage_link

# Competitor link stripping
html_with_competitor = '<p>Try <a href="https://oakley.com/sutro">Oakley Sutro</a> or our glasses.</p>'
fixed, stripped = strip_competitor_links(html_with_competitor)
assert "oakley.com" in stripped
assert 'href="https://oakley.com' not in fixed
assert "Oakley Sutro" in fixed
print(f"   ✓ Competitor link stripped, anchor text preserved")

# Homepage link injection
html_no_hp = '<p>Premium cycling sunglasses.</p>'
fixed2, injected = ensure_homepage_link(html_no_hp)
assert injected and 'href="/"' in fixed2
print(f"   ✓ Homepage link injection working")

# Hard-fail on bad article
bad_post = {"title": "Random Title", "body_html": "<p>too short</p>",
            "meta_description": "x", "keyword": "best cycling sunglasses"}
brief_min = {"primary_keyword": "best cycling sunglasses", "topic": "x"}
r = gate(bad_post, brief_min, "US", None)
assert not r["passed"]
assert len(r["hard_issues"]) >= 2
print(f"   ✓ Bad article hard-fails ({len(r['hard_issues'])} issues)")
print("✅ Step 1: Quality gate behaves correctly")

# ── 2. Localization briefs build for all 10 non-US locales ───
print("\n🌍 Step 2: Localization briefs (mechanical, no LLM)")
from briefs.localization_brief import build_all_localization_briefs
fake_master = {"topic": "best cycling sunglasses",
                "primary_keyword": "best cycling sunglasses",
                "search_intent": "commercial investigation"}
fake_research = {"paa": {}, "serps": {"snapshots": []}, "ai_overviews": {}, "competitors": {}}
fake_commercial = {
    "NL": {"current_price": 69, "currency": "EUR", "offer_status": "test"},
    "DE": {"current_price": 149, "currency": "EUR", "offer_status": "standard"},
}
local_briefs = build_all_localization_briefs(fake_master, fake_research, fake_commercial)
assert len(local_briefs) >= 9
assert local_briefs["nl"]["local_adaptation_notes"]
assert "69 EUR" in " ".join(local_briefs["nl"]["local_adaptation_notes"]) \
    or local_briefs["nl"]["commercial"]["current_price"] == 69
print(f"   ✓ {len(local_briefs)} locale briefs built (NL price=69 EUR, DE price=149 EUR)")
print("✅ Step 2: localization briefs land in output/localization_briefs/")

# ── 3. Master brief — Haiku-enriched (real $0.01 call) ───────
print("\n📋 Step 3: Master brief (mechanical + Haiku enrichment, ~$0.01)")
from briefs.us_master_brief import build_brief
fake_decision = {
    "chosen_keyword":     "best cycling sunglasses",
    "chosen_action":      "create_new_article",
    "opportunity_score":  75,
    "sub_scores":         {"buyer_intent": 90, "product_fit": 90},
    "target_market":      "US",
}
# Use empty research/inventory so we test the offline path; brief should still produce something
master = build_brief(fake_decision, {"paa": {}, "competitors": {}, "ai_overviews": {}},
                     {"articles": [], "collections": []})
assert master["primary_keyword"] == "best cycling sunglasses"
assert master["velluto_position"]["main_angle"]
assert master["do_not_claim"]  # Haiku should populate these
assert master["target_reader"]
assert master["internal_links"]
print(f"   ✓ Brief has {len(master['must_answer_questions'])} PAA questions, "
      f"{len(master['do_not_claim'])} claims-to-avoid, "
      f"{len(master['internal_links'])} internal links")
print(f"   ✓ Main angle: '{master['velluto_position']['main_angle'][:80]}…'")
print("✅ Step 3: Master brief built with Haiku enrichment")

# ── 4. Brief flows into generate_de_primary prompt ───────────
print("\n🔗 Step 4: Brief threads into Sonnet prompt")
# Patch Anthropic before importing seo_bot
import anthropic
anthropic.Anthropic = lambda **kw: _FakeClient()
captured_prompts.clear()

import seo_bot
fake_products = [{"title": "Velluto StradaPro — Nero",
                  "url": "https://velluto-shop.com/products/strada-pro",
                  "image": "https://cdn/img.jpg", "handle": "strada-pro"}]
fake_kw = {"keyword": "best cycling sunglasses", "art_num": "099",
            "keyword_en": "best cycling sunglasses", "keyword_de": "Rennradbrille"}
fake_quality = {"day": 5, "word_count": 1800, "faq_count": 5}

try:
    seo_bot.generate_de_primary(fake_kw, fake_products, fake_quality, brief=master)
except Exception:
    pass  # generation parse will fail on the stub; we only care about the prompt

assert captured_prompts, "❌ generate_de_primary made no API call"
prompt = captured_prompts[0]["messages"][0]["content"]
assert "MASTER BRIEF" in prompt, "❌ Brief block not in prompt"
assert master["velluto_position"]["main_angle"] in prompt or "main_angle" in prompt.lower()
print(f"   ✓ Brief MASTER BRIEF block injected into Sonnet prompt "
      f"({prompt.count('MASTER BRIEF')} occurrence)")
if master["do_not_claim"]:
    first_claim = master["do_not_claim"][0][:30]
    assert first_claim in prompt, f"❌ claims_to_avoid '{first_claim}' missing"
    print(f"   ✓ claims_to_avoid section threaded through")
print("✅ Step 4: Brief drives the Sonnet prompt")

# ── 5. End-to-end gate pass on a well-formed post ────────────
print("\n🎯 Step 5: Quality gate accepts a well-formed post")
good_post = {
    "title": "Best Cycling Sunglasses 2026: A Buying Guide",  # contains primary keyword
    "body_html": (
        "<h1>Best Cycling Sunglasses for Road Cycling</h1>"
        + "<p>Lorem ipsum about UV400 and anti-fog protection. " + ("Filler text. " * 400) + "</p>"
        + "<h2>What are the best cycling sunglasses?</h2><p>Look for UV400. "
        + ("Filler text. " * 300) + "</p>"
        + '<p>Discover <a href="https://velluto-shop.com/products/strada-pro">Velluto Strada Pro</a>.</p>'
    ),
    "meta_description": "Find the best cycling sunglasses with UV400, anti-fog and Italian design.",
    "keyword": "best cycling sunglasses",
}
brief_with_paa = {**master, "must_answer_questions": ["What are the best cycling sunglasses?"]}
r = gate(good_post, brief_with_paa, "US", None)
assert r["passed"], f"❌ Good post should pass: {r['hard_issues']}"
print(f"   ✓ Good article passed gate (auto_fixes: {len(r['auto_fixes'])})")
print("✅ Step 5: Quality gate accepts well-formed articles")

# ── 6. Output files persisted ───────────────────────────────
expected = [
    f"output/us_master_brief_{__import__('datetime').date.today().isoformat()}.json",
    "output/localization_briefs/nl.json",
    "output/localization_briefs/de.json",
]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for rel in expected:
    p = os.path.join(root, rel)
    assert os.path.exists(p), f"❌ missing: {rel}"
print(f"\n✅ Step 6: All Phase 4 output files persisted")

print("\n" + "=" * 60)
print("🎉 Phase 4 smoke test PASSED")
print("=" * 60)
