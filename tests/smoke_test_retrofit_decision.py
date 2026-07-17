"""
Smoke test for decision-driven retrofit wiring (content_retrofit.retrofit_for_decision).

Covers the pure logic that decides WHICH article a daily 'update_existing_article'
decision maps to, and WHETHER a cooldown blocks it — no network, no LLM.

Run: python3 tests/smoke_test_retrofit_decision.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import content_retrofit as cr

fails = []
def ok(cond, label):
    print(("   ✓ " if cond else "   ✗ FAIL ") + label)
    if not cond:
        fails.append(label)

AUDIT = {
    "https://x/blogs/m/oakley-alternative-cycling-sunglasses-why-riders-switch": {
        "title": "Oakley Alternative Cycling Sunglasses: Why Riders Switch",
        "handle": "oakley-alternative-cycling-sunglasses-why-riders-switch"},
    "https://x/blogs/m/best-cycling-glasses-2026": {
        "title": "Best Cycling Glasses 2026",
        "handle": "best-cycling-glasses-2026"},
    "https://x/blogs/m/anti-fog-cycling-guide": {
        "title": "Anti Fog Cycling Guide",
        "handle": "anti-fog-cycling-guide"},
}

print("=== Keyword → existing article mapping ===")
# Plural/singular tolerated: 'oakley alternatives' → the oakley-alternative article
ok(cr._match_article(AUDIT, "oakley alternatives", "oakley alternatives") ==
   "https://x/blogs/m/oakley-alternative-cycling-sunglasses-why-riders-switch",
   "'oakley alternatives' → oakley-alternative article")
# No real match → None (falls through to new-article creation, not a random edit)
ok(cr._match_article(AUDIT, "titanium frame durability") is None,
   "'titanium frame durability' → None (no match)")
# A single distinctive token is not enough (needs >= 2 overlap)
ok(cr._match_article(AUDIT, "oakley") is None,
   "'oakley' alone → None (needs >= 2 tokens)")
# Generic filler words alone don't match anything
ok(cr._match_article(AUDIT, "best cycling glasses") is not None,
   "'best cycling glasses' → matches (2+ real tokens)")

print("\n=== Cooldown gating (shared with the 28-day cycle) ===")
today = datetime.date(2026, 7, 17)
ok(cr.is_on_cooldown("u", {"articles": {"u": {"date": "2026-07-01"}}}, {}, today) is True,
   "retrofitted 16d ago (< 56d COOLDOWN) → blocked")
ok(cr.is_on_cooldown("u", {"articles": {"u": {"date": "2026-04-01"}}}, {}, today) is False,
   "retrofitted >56d ago → allowed")
ok(cr.is_on_cooldown("u", {}, {"u": {"last_optimized": "2026-07-10"}}, today) is True,
   "CTR-optimized 7d ago (< 14d quiet) → blocked")
ok(cr.is_on_cooldown("u", {}, {}, today) is False,
   "never touched → allowed")

print("\n" + ("✅ ALL PASSED" if not fails else f"❌ {len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
