"""
Smoke test for the shared legal self-heal module (briefs.legal_heal).

Covers the parts that need NO Anthropic client (so it runs in CI without keys):
  - _mechanical: exact, LLM-free fixes (strip "(stated)", "Tested & Ranked", em-dashes,
    correct a false Dutch origin)
  - _exact_flags: surfaces the EXACT risky substrings incl. the new superlative /
    price-disparagement categories
  - heal_post: a clean post is reported clean without any LLM call

The LLM find/replace path (compliance_edit with real edits) is exercised live by
scripts/legal_retrofit.py --rewrite and seo_bot's pre-publish check.

Run: python3 tests/smoke_test_legal_heal.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from briefs.legal_heal import _mechanical, _exact_flags, heal_post
from briefs.quality_gate import check_compliance

fails = []
def ok(cond, label):
    print(("   ✓ " if cond else "   ✗ FAIL ") + label)
    if not cond:
        fails.append(label)


print("=== _mechanical (LLM-free exact fixes) ===")
t, m, b = _mechanical("Best Cycling Sunglasses, Tested & Ranked",
                      "UV400 (stated) protection",
                      "<p>Velluto is a Dutch brand — great value.</p>")
ok("tested" not in t.lower() and "ranked" not in t.lower(), "strips 'Tested & Ranked' from title")
ok("(stated)" not in m.lower(), "strips '(stated)' from meta")
ok("dutch" not in b.lower() and "german" in b.lower(), "corrects false Dutch origin → German")
ok("—" not in (t + m + b), "removes em-dash")

print("\n=== _exact_flags (surfaces the risky substrings) ===")
flags = _exact_flags("One of them is lighter than anything Oakley makes. "
                     "With Oakley you are subsidising a marketing department. "
                     "The Oakley Sutro is overpriced.")
joined = " || ".join(flags).lower()
ok(any("than anything" in f.lower() for f in flags), "flags the superlative 'than anything'")
ok("subsidising a marketing" in joined or "marketing department" in joined,
   "flags 'subsidise a marketing department'")
ok("overpriced" in joined, "flags 'overpriced'")

print("\n=== heal_post: clean post needs no LLM ===")
clean = {"title": "Best Road Cycling Sunglasses in 2026",
         "meta_description": "UV400 certified, 25 g, anti-fog cycling eyewear.",
         "body_html": "<p>The Velluto StradaPro weighs 25 g with UV400 certified lenses. "
                      "Oakley's Sutro is a well-known road option.</p>"}
ok(not check_compliance(clean), "sample post is already compliant (precondition)")
ok(heal_post(clean, client=None, lang_name="English") is True,
   "heal_post returns True for a clean post WITHOUT touching the client")

print("\n" + ("✅ ALL PASSED" if not fails else f"❌ {len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
