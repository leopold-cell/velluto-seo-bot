"""
Smoke test for the EU/German advertising-law guardrails (quality_gate.check_compliance).

NOT legal advice — verifies the pattern backstop for the highest-risk phrasings:
  - fabricated tests / reviews / first-hand experience (§ 5/5a UWG + EU Omnibus)
  - disparaging / doubt-casting competitor phrasing (§ 6 Abs. 2 Nr. 5 UWG)
  - false brand origin (§ 5 UWG) — Velluto is a GERMAN brand
and that honest, spec-based brand content is NOT blocked.

Run: python3 tests/smoke_test_legal_compliance.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from briefs.quality_gate import check_compliance

fails = []
def ok(cond, label):
    print(("   ✓ " if cond else "   ✗ FAIL ") + label)
    if not cond:
        fails.append(label)

def flagged(html):
    return bool(check_compliance({"body_html": html}))

print("=== MUST flag (legal risk) ===")
ok(flagged("<p>We tested the StradaPro over 200 km of riding.</p>"), "'we tested … km'")
ok(flagged("<p>In our lab the lenses scored highest.</p>"), "'in our lab'")
ok(flagged("<p>Hands-on, the fit felt secure.</p>"), "'hands-on'")
ok(flagged("<p>Testsieger 2026 in our editorial test.</p>"), "'Testsieger / editorial test'")
ok(flagged("<p>After 6 weeks of testing we concluded it wins.</p>"), "'after N weeks of testing'")
ok(flagged("<p>SunGod lists UV400 (stated) while Velluto is certified.</p>"), "'(stated)' asymmetry")
ok(flagged("<p>Oakley coatings degrade after thirty washes.</p>"), "competitor 'degrade' (disparagement)")
ok(flagged("<p>SunGod lenses are inferior and cheaply made.</p>"), "competitor 'inferior / cheaply made'")
ok(flagged("<p>One of them is lighter than anything Oakley makes for road cycling.</p>"),
   "unverifiable superlative vs competitor ('lighter than anything Oakley')")
ok(flagged("<p>The Rudy Project frame is better than any option in the category.</p>"),
   "vague comparative 'better than any' near competitor")
ok(flagged("<p>With Oakley you are just subsidising a marketing department.</p>"),
   "price disparagement ('subsidise a marketing department')")
ok(flagged("<p>That gap, between what Oakley charges and what you need, is the point.</p>"),
   "price disparagement ('what Oakley charges')")
ok(flagged("<p>The Oakley Sutro is overpriced for what it offers.</p>"),
   "price disparagement ('overpriced' near competitor)")
ok(flagged("<p>You are really just paying for the logo with Oakley.</p>"),
   "price disparagement ('paying for the logo')")
ok(flagged("<p>Velluto is a Dutch cycling eyewear brand.</p>"), "false origin 'Dutch Velluto'")
ok(flagged("<p>De Nederlandse fietsbril van Velluto.</p>"), "false origin 'Nederlands … Velluto'")

print("\n=== MUST NOT flag (honest brand content) ===")
ok(not flagged("<p>The StradaPro weighs 25 g and has UV400 certified protection.</p>"),
   "own documented claim (25 g, UV400 certified)")
ok(not flagged("<p>SunGod offers a coating-based anti-fog system; Velluto uses a built-in vent.</p>"),
   "neutral competitor fact (no disparagement)")
ok(not flagged("<p>Velluto is a German brand with Italian design.</p>"),
   "correct origin (German)")
ok(not flagged("<p>Premium cycling glasses range from 150 to 350 EUR.</p>"),
   "market price range")
ok(not flagged("<p>Many riders try different lens tints before choosing.</p>"),
   "generic 'try/test' wording, no first-hand claim")
ok(not flagged("<p>The StradaPro weighs merely 25 grams and coatings can degrade over years.</p>"),
   "neutral 'merely'/'degrade' with NO competitor → NOT flagged")
ok(not flagged("<p>The StradaPro weighs 25 g, lighter than the 32 g category average.</p>"),
   "bounded, verifiable weight comparison ('lighter than the 32 g average') → NOT flagged")
ok(not flagged("<p>Oakley's Sutro is a well-known, respected road option.</p>"),
   "neutral/positive competitor mention → NOT flagged")
ok(not flagged("<p>Premium road frames often cost 200 to 350 EUR; Velluto starts at 69 EUR.</p>"),
   "factual own price + market range, no disparagement → NOT flagged")
ok(not flagged("<p>Riders love that the StradaPro is lighter than they expect.</p>"),
   "own claim 'lighter than they expect', no competitor → NOT flagged")

print("\n" + ("✅ ALL PASSED" if not fails else f"❌ {len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
