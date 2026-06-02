"""
Phase 4.11 smoke test — em-dash removal (the AI-writing tell).
No network. Run: python3 tests/smoke_test_phase4_11.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from briefs.quality_gate import strip_em_dashes, gate

print("=" * 60)
print("=== Phase 4.11 Smoke Test — em-dash banishment ===")
print("=" * 60)

# 1. Em-dash / spaced en-dash → comma
print("\n✂️  Step 1: em-dash + spaced en-dash → comma")
for inp, exp in [
    ("Klare Sicht — auch bei Wind.",      "Klare Sicht, auch bei Wind."),
    ("25g, UV400 — der Sweet Spot.",      "25g, UV400, der Sweet Spot."),
    ("Sicht klar—immer.",                 "Sicht klar, immer."),
    ("Best value – tested in 2026.",      "Best value, tested in 2026."),
]:
    out, _ = strip_em_dashes(inp)
    assert "—" not in out and " – " not in out, f"dash remained: {out!r}"
    print(f"   ✓ {inp!r} → {out!r}")

# 2. Preserve hyphens, number ranges, URLs
print("\n🛡️  Step 2: preserve hyphens / ranges / URLs")
for s in ["anti-fog", "UV400-certified", "30-day trial", "10–20 km",
          "/anti-fog-cycling-sunglasses", "high-contrast lenses"]:
    out, changed = strip_em_dashes(s)
    assert out == s, f"❌ should NOT change {s!r} → {out!r}"
    print(f"   ✓ unchanged: {s!r}")

# 3. gate() auto-fix end-to-end
print("\n🚦 Step 3: gate() strips em-dashes as an auto-fix")
post = {
    "title": "best cycling glasses",
    "keyword": "best cycling glasses",
    "body_html": ("<h1>Best cycling glasses</h1>"
                  "<p>Klare Sicht — auch bei Wind. Anti-fog bleibt. 10–20 km Reichweite. "
                  + ("filler " * 200) + "</p>"
                  '<p><a href="https://velluto-shop.com">Velluto</a></p>'),
}
r = gate(post, {"primary_keyword": "best cycling glasses", "topic": "x"}, "US", None)
assert "—" not in post["body_html"], "em-dash still in body after gate"
assert "replaced em-dashes with commas" in r["auto_fixes"], "auto-fix not logged"
assert "10–20" in post["body_html"], "number range wrongly altered"
assert "Anti-fog" in post["body_html"], "hyphen wrongly altered"
print(f"   ✓ body em-dash-free, ranges + hyphens intact, auto-fix logged")

# 4. No regression: an already-clean body is left unchanged by strip
print("\n✅ Step 4: clean body unchanged")
clean = "<p>UV400 protection, anti-fog ventilation, 30-day trial.</p>"
out, changed = strip_em_dashes(clean)
assert out == clean and not changed
print("   ✓ clean body: no change, changed flag False")

print("\n" + "=" * 60)
print("🎉 Phase 4.11 smoke test PASSED")
print("=" * 60)
