"""
Phase 4.4 smoke test — sentence-aware FACT check.

Verifies:
  - Velluto-attributed claims still get blocked (safety preserved)
  - Competitor mentions DON'T get blocked (the bug we fixed)
  - Informational/FAQ context doesn't block (the bug we fixed)
  - Sentences with BOTH brands → competitor wins (negation cases)

No network, no LLM calls. ~0.1 seconds.

Run: python3 tests/smoke_test_phase4_4.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from briefs.quality_gate import check_brand_facts, FORBIDDEN_FEATURE_TOKENS

print("=" * 60)
print("=== Phase 4.4 Smoke Test — Sentence-aware FACT check ===")
print("=" * 60)

# ── 1. Velluto-attributed claims must be flagged ────────────
print("\n🔴 Step 1: Velluto-attributed claims should still get blocked")

case_a = {"body_html": "<p>The Velluto StradaPro's polarized lenses cut glare.</p>"}
issues = check_brand_facts(case_a)
assert any("polarized" in i for i in issues), f"❌ Should flag Velluto polarized claim: {issues}"
print(f"   ✓ 'Velluto's polarized lenses' → flagged ({issues[0]})")

case_b = {"body_html": "<p>Velluto uses photochromic technology for shifting light.</p>"}
issues = check_brand_facts(case_b)
assert any("photochromic" in i for i in issues), f"❌ Should flag Velluto photochromic claim: {issues}"
print(f"   ✓ 'Velluto uses photochromic' → flagged ({issues[0]})")

# ── 2. Competitor mentions must NOT be flagged ──────────────
print("\n🟢 Step 2: Competitor-attributed mentions should NOT block")

case_c = {"body_html": "<p>Oakley's Prizm lenses are polarized; Velluto chose UV400 instead.</p>"}
issues = check_brand_facts(case_c)
assert not issues, f"❌ Should NOT flag Oakley polarized in competitor context: {issues}"
print("   ✓ 'Oakley's Prizm lenses are polarized; Velluto chose UV400' → NOT flagged")

case_d = {"body_html": "<p>Rudy Project offers photochromic lenses. Velluto offers interchangeable lenses.</p>"}
issues = check_brand_facts(case_d)
assert not issues, f"❌ Should NOT flag Rudy photochromic in competitor context: {issues}"
print("   ✓ 'Rudy Project offers photochromic. Velluto offers interchangeable.' → NOT flagged")

# ── 3. Informational / FAQ context must NOT be flagged ─────
print("\n🟢 Step 3: Informational / FAQ mentions should NOT block")

case_e = {"body_html": "<p>Are polarized lenses worth it for road cycling?</p>"}
issues = check_brand_facts(case_e)
assert not issues, f"❌ Should NOT flag bare FAQ mention: {issues}"
print("   ✓ 'Are polarized lenses worth it for cycling?' → NOT flagged")

case_f = {"body_html": "<h2>Photochromic vs interchangeable: which for cycling?</h2><p>Both approaches have merit.</p>"}
issues = check_brand_facts(case_f)
assert not issues, f"❌ Should NOT flag photochromic in comparison heading: {issues}"
print("   ✓ 'Photochromic vs interchangeable' (heading) → NOT flagged")

# ── 4. Negation: 'Velluto doesn't offer X' with competitor nearby ──
print("\n🟢 Step 4: Negation sentences (Velluto + competitor in same sentence)")

case_g = {"body_html": "<p>Velluto doesn't offer polarized; Oakley does.</p>"}
issues = check_brand_facts(case_g)
assert not issues, f"❌ Should NOT flag 'Velluto doesn't offer' negation: {issues}"
print("   ✓ 'Velluto doesn't offer polarized; Oakley does' → NOT flagged (competitor wins)")

# ── 5. Realistic Oakley-alternative article that should publish ───
print("\n🟢 Step 5: Realistic Oakley-alternative article (the failing case)")

case_h = {"body_html": (
    "<h1>Oakley Alternative Cycling Sunglasses</h1>"
    "<p>Looking for cycling glasses that match Oakley quality without the price?</p>"
    "<h2>What Oakley does well</h2>"
    "<p>Oakley's Prizm lens technology adds contrast. Many of their road models are also polarized, which cuts glare from wet asphalt.</p>"
    "<h2>What Velluto offers instead</h2>"
    "<p>Velluto Strada Pro uses an interchangeable-lens system. Swap a clear lens for grey or amber depending on conditions. UV400 across all tints.</p>"
    "<h2>FAQ</h2>"
    "<p>Are polarized lenses important for cycling? They reduce glare but can interfere with seeing wet patches and digital displays.</p>"
)}
issues = check_brand_facts(case_h)
assert not issues, f"❌ Realistic comparison should publish cleanly: {issues}"
print(f"   ✓ Full Oakley-vs-Velluto comparison article → NOT flagged ({len(issues)} issues)")

# ── 6. False-positive check: 'photochromic-style' in Velluto context ─
print("\n🔴 Step 6: Subtle false claim — adjective form near Velluto")

case_i = {"body_html": "<p>The Velluto StradaPro features photochromic-like adaptation.</p>"}
issues = check_brand_facts(case_i)
assert any("photochrom" in i for i in issues), f"❌ Should flag photochromic-like Velluto claim: {issues}"
print("   ✓ 'Velluto StradaPro features photochromic-like' → flagged (good)")

# ── 7. Sanity: forbidden tokens list is sane ───────────────
print("\n🔧 Step 7: Forbidden-tokens config sanity")
assert len(FORBIDDEN_FEATURE_TOKENS) >= 2
assert any(t[0] == "photochrom" for t in FORBIDDEN_FEATURE_TOKENS)
assert any(t[0] == "polari" for t in FORBIDDEN_FEATURE_TOKENS)
print(f"   ✓ {len(FORBIDDEN_FEATURE_TOKENS)} forbidden tokens registered: "
      f"{[t[0] for t in FORBIDDEN_FEATURE_TOKENS]}")

print("\n" + "=" * 60)
print("🎉 Phase 4.4 smoke test PASSED")
print("=" * 60)
