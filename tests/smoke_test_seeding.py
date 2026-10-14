"""
Smoke test for the seeding pipeline: target classification and outreach selection.

Regression guards for the bugs found in the first review:
  - .lstrip("www.") stripped characters, turning wielrenner.eu into ielrenner.eu
  - competitor brands (canyon, siroko, poc.com) were filed as "editorial" targets
  - search engines / social networks ranked as seeding targets
  - marketplaces ended up in stockist outreach
and that outreach never re-pitches a domain inside the resend window.

Run: python3 tests/smoke_test_seeding.py
"""
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import seeding_outreach as so
import seeding_targets as st

fails = []
def ok(cond, label):
    print(("   ✓ " if cond else "   ✗ FAIL ") + label)
    if not cond:
        fails.append(label)

print("domain normalisation")
ok(st._norm("www.wielrenner.eu") == "wielrenner.eu", "www. prefix removed")
ok(st._norm("wielrenner.eu") == "wielrenner.eu", "leading 'w' of the host survives")
ok(st._norm("www.wiggle.co.uk") == "wiggle.co.uk", "wiggle keeps its w")

print("classification")
for dom, want in [("canyon.com", "brand"), ("siroko.com", "brand"), ("poc.com", "brand"),
                  ("google.com", "skip"), ("facebook.com", "skip"),
                  ("nakedoptics.net", "retailer"), ("sigmasports.com", "retailer"),
                  ("wiggle.co.uk", "retailer"), ("cyclingweekly.com", "editorial"),
                  ("youtube.com", "youtube"), ("reddit.com", "reddit"),
                  ("velluto-shop.com", "own")]:
    ok(st.classify(dom) == want, f"{dom} -> {want}")

print("outreach selection")
today = dt.date.today()
data = {"seeding": [
            {"domain": "a.com", "type": "editorial", "score": 300},
            {"domain": "b.com", "type": "editorial", "score": 200},
            {"domain": "reddit.com", "type": "reddit", "score": 400}],
        "stockist": [{"domain": "shop.de", "type": "retailer", "score": 100}]}
picked = [t["domain"] for t, _ in so._pick_targets(data, {}, 10)]
ok("reddit.com" not in picked, "Reddit is never pitched by mail")
ok(picked == ["a.com", "b.com", "shop.de"], "ordered by score, stockists included")
recent = {"a.com": {"drafted": (today - dt.timedelta(days=5)).isoformat()}}
ok("a.com" not in [t["domain"] for t, _ in so._pick_targets(data, recent, 10)],
   "no re-pitch inside the resend window")
old = {"a.com": {"drafted": (today - dt.timedelta(days=60)).isoformat()}}
ok("a.com" in [t["domain"] for t, _ in so._pick_targets(data, old, 10)],
   "eligible again after the window")
due = so._follow_ups({"x.com": {"drafted": (today - dt.timedelta(days=15)).isoformat()},
                      "y.com": {"drafted": (today - dt.timedelta(days=3)).isoformat()},
                      "z.com": {"drafted": (today - dt.timedelta(days=15)).isoformat(),
                                "replied": True}})
ok(len(due) == 1 and due[0].startswith("x.com"), "follow-up only for unanswered pitches past 14 days")

print("fact gate")
ok(bool(so._issues("Hi", "The Velluto StradaPro has polarized lenses.")),
   "false spec in a pitch is blocked")
ok(not so._issues("Hi", "Velluto StradaPro: 25 g, UV400, interchangeable lenses. Free sample, no obligation."),
   "honest spec pitch passes")

print("link_builder cannot post to Reddit")
import link_builder
ok(link_builder.post_to_reddit({"topic": "x"})["status"] == "skipped", "auto-poster disabled")

print()
if fails:
    print(f"❌ {len(fails)} failed")
    sys.exit(1)
print("✅ all passed")
