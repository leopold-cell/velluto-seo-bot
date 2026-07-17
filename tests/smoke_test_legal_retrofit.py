"""
Smoke test for the legal-compliance retrofit classifier (scripts/legal_retrofit.py).

Verifies the DRAFT vs REVIEW vs clean routing — no network. NOT legal advice.

Run: python3 tests/smoke_test_legal_retrofit.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = ["legal_retrofit"]  # avoid --apply during import

from scripts.legal_retrofit import classify

fails = []
def ok(cond, label):
    print(("   ✓ " if cond else "   ✗ FAIL ") + label)
    if not cond:
        fails.append(label)

# High-confidence legal risk → DRAFT
r = classify("SunGod vs Velluto Tested", "<p>We tested both over 300 km of riding.</p>")
ok(bool(r["draft_reasons"]), "fabricated test → draft")
r = classify("X", "<p>Their coating degrades after 30 washes; UV400 (stated).</p>")
ok(bool(r["draft_reasons"]), "disparagement + '(stated)' → draft")

# Lower-confidence → REVIEW (not auto-drafted)
r = classify("X", "<p>Velluto is a Dutch cycling brand.</p>")
ok(bool(r["review_reasons"]) and not r["draft_reasons"], "false 'Dutch' origin → review only")

# Clean honest comparison → nothing
r = classify("Best cycling glasses",
             "<p>Velluto weighs 25 g with UV400 certified lenses. SunGod uses a "
             "coating-based anti-fog system.</p>")
ok(not r["draft_reasons"] and not r["review_reasons"], "honest spec comparison → clean")

print("\n" + ("✅ ALL PASSED" if not fails else f"❌ {len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
