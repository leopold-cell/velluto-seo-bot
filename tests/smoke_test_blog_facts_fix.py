"""
Smoke test for the 2026-07-15 publish-outage fix.

Root cause: un-attributed FORBIDDEN_CLAIMS regexes (mirrored / tinted /
prescription / over-glasses) matched competitor & informational lens mentions
ANYWHERE in premium comparison articles → hard-blocked every publish.

Fix: those checks are now sentence-aware in check_brand_facts (competitor and
informational mentions pass, Velluto-attributed claims still block); "tinted"
was dropped (Velluto DOES offer tinted Puro/Visione lenses); and the price check
skips clearly-higher comparison-context prices.

No network, no LLM. Run: python3 tests/smoke_test_blog_facts_fix.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from briefs.quality_gate import check_brand_facts, check_commercial_config, gate

fails = []
def ok(cond, label):
    print(("   ✓ " if cond else "   ✗ FAIL ") + label)
    if not cond:
        fails.append(label)

print("=== Brand-fact check: mirrored / prescription / over-glasses ===")

# Velluto-attributed → MUST still block (safety preserved)
ok(any("mirror" in i for i in check_brand_facts(
    {"body_html": "<p>Velluto's StradaPro uses a mirrored lens coating.</p>"})),
   "Velluto mirrored lens → flagged")
ok(any("prescription" in i for i in check_brand_facts(
    {"body_html": "<p>The Velluto StradaPro offers a prescription lens insert.</p>"})),
   "Velluto prescription insert → flagged")
ok(any("over" in i.lower() for i in check_brand_facts(
    {"body_html": "<p>The Velluto StradaPro fits over your prescription glasses.</p>"})),
   "Velluto over-glasses claim → flagged")

# Competitor-attributed → MUST pass (the bug we fixed)
ok(not check_brand_facts(
    {"body_html": "<p>Oakley's Prizm range includes mirrored lenses; Velluto uses interchangeable clear and high-contrast lenses.</p>"}),
   "competitor mirrored lenses → NOT flagged")
ok(not check_brand_facts(
    {"body_html": "<p>Rudy Project sells prescription inserts. Velluto offers click-in lenses instead.</p>"}),
   "competitor prescription insert → NOT flagged")

# Informational / bare mention (no brand) → MUST pass
ok(not check_brand_facts(
    {"body_html": "<p>Mirrored lenses reduce glare on bright days.</p>"}),
   "informational mirrored lenses → NOT flagged")

# "tinted lens" is a legit Velluto feature now → MUST pass even Velluto-attributed
ok(not check_brand_facts(
    {"body_html": "<p>Velluto's Visione is a high-contrast tinted lens for grey days.</p>"}),
   "Velluto tinted lens (Puro/Visione) → NOT flagged")

print("\n=== Commercial price check: comparison context ===")
US = {"US": {"current_price": 69, "currency": "EUR"}}

# Clearly-higher price in comparison context → market context, NOT flagged
ok(not check_commercial_config(
    {"body_html": "<p>Velluto rivals premium brands charging up to 300 EUR.</p>"}, "US", US),
   "'Velluto rivals brands ... up to 300 EUR' → NOT flagged")
ok(not check_commercial_config(
    {"body_html": "<p>Where competitors cost 99 EUR, Velluto keeps it accessible.</p>"}, "US", US),
   "'competitors cost 99 EUR' → NOT flagged")

# Near-miss Velluto price (real typo) → MUST still flag
ok(any("PRICE" in i for i in check_commercial_config(
    {"body_html": "<p>The Velluto StradaPro starts at 70 EUR.</p>"}, "US", US)),
   "Velluto '70 EUR' (should be 69) → flagged")
# Exact price → pass
ok(not check_commercial_config(
    {"body_html": "<p>The Velluto StradaPro starts at 69 EUR.</p>"}, "US", US),
   "Velluto '69 EUR' exact → NOT flagged")

# Free-shipping threshold → NOT the product price → must NOT flag (the recurring
# false positive that regenerated whole articles).
ok(not check_commercial_config(
    {"body_html": "<p>Velluto offers free shipping on orders over 89 EUR.</p>"}, "US", US),
   "Velluto 'free shipping over 89 EUR' → NOT flagged")
ok(not check_commercial_config(
    {"body_html": "<p>Velluto: kostenlose Lieferung ab 89 EUR.</p>"}, "US", US),
   "Velluto 'kostenlose Lieferung ab 89 EUR' → NOT flagged")
# But a bare wrong Velluto price with NO shipping context still flags.
ok(any("PRICE" in i for i in check_commercial_config(
    {"body_html": "<p>The Velluto StradaPro costs 89 EUR.</p>"}, "US", US)),
   "Velluto '89 EUR' as price (no shipping context) → flagged")

print("\n=== Meta description auto-fix ===")
long_md = "x" * 175
p = {"title": "Best cycling glasses 2026", "meta_description": long_md,
     "body_html": "<h1>Best cycling glasses 2026</h1><p>" + ("word " * 700) +
                  '</p><p><a href="https://velluto-shop.com">Velluto</a></p>'}
res = gate(p, brief=None, market_code="US", commercial=US)
ok(len(p["meta_description"]) <= 160, f"meta trimmed to {len(p['meta_description'])} ≤ 160")
ok(not any("META" in i for i in res["hard_issues"]),
   "no [META] hard issue after auto-fix")

print("\n" + ("✅ ALL PASSED" if not fails else f"❌ {len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
