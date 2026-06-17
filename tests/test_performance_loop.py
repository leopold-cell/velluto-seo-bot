"""
Phase 5 performance-loop tests — pure (no disk writes, no GSC credentials).

Run:  python tests/test_performance_loop.py
Verifies: tier classification, the 0→1-click dormant guard, audit report
rendering, and that the opportunity scorer turns feedback into scored
scale/refresh candidates with the momentum boost applied.
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from performance import classifier, audit              # noqa: E402
from decision import opportunity_scorer as scorer      # noqa: E402

B = "https://velluto-shop.com/blogs/velluto-the-magazine/"


def _sample_gsc() -> dict:
    return {
        "date": datetime.date.today().isoformat(),
        "windows": {"current": ["2026-05-20", "2026-06-17"],
                    "previous": ["2026-04-22", "2026-05-19"]},
        "per_page_deltas": [
            {"page": B + "winner-a", "curr_impressions": 4200, "prev_impressions": 1800,
             "impr_delta_pct": 133.3, "curr_clicks": 140, "prev_clicks": 60, "clicks_delta_pct": 133.3},
            {"page": B + "winner-b", "curr_impressions": 900, "prev_impressions": 850,
             "impr_delta_pct": 5.9, "curr_clicks": 30, "prev_clicks": 28, "clicks_delta_pct": 7.1},
            {"page": B + "riser", "curr_impressions": 600, "prev_impressions": 120,
             "impr_delta_pct": 400.0, "curr_clicks": 6, "prev_clicks": 1, "clicks_delta_pct": 500.0},
            {"page": B + "decayer", "curr_impressions": 700, "prev_impressions": 1500,
             "impr_delta_pct": -53.3, "curr_clicks": 12, "prev_clicks": 45, "clicks_delta_pct": -73.3},
            {"page": B + "dormant", "curr_impressions": 2000, "prev_impressions": 1900,
             "impr_delta_pct": 5.3, "curr_clicks": 1, "prev_clicks": 0, "clicks_delta_pct": 100.0},
            {"page": "https://velluto-shop.com/products/p", "curr_impressions": 300,
             "prev_impressions": 290, "impr_delta_pct": 3.4, "curr_clicks": 9, "prev_clicks": 8,
             "clicks_delta_pct": 12.5},
        ],
        "striking_distance_queries": [
            {"query": "oakley alternative", "page": B + "winner-a",
             "impressions": 1200, "clicks": 40, "ctr_pct": 3.3, "avg_position": 9.1},
        ],
        "totals": {"curr_impressions": 8700, "curr_clicks": 198, "prev_impressions": 6460,
                   "prev_clicks": 142, "impr_delta_pct": 34.7, "clicks_delta_pct": 39.4},
    }


def _sample_inventory() -> dict:
    return {"articles": [
        {"id": 111, "title": "Winner A", "handle": "winner-a",
         "url": B + "winner-a", "primary_keyword": "winner a kw"},
        {"id": 333, "title": "Decayer", "handle": "decayer",
         "url": B + "decayer", "primary_keyword": "decayer kw"},
    ], "collections": []}


def test_classification():
    fb = classifier.classify(gsc=_sample_gsc(), inventory=_sample_inventory())
    tiers = {t: [r["url"] for r in rows] for t, rows in fb["tiers"].items()}
    assert len(tiers["winner"]) == 2, tiers["winner"]
    assert B + "riser" in tiers["rising"], tiers["rising"]
    assert B + "decayer" in tiers["decaying"], tiers["decaying"]
    # The 0→1 click guard: high impressions, 1 click must be dormant, NOT rising.
    assert B + "dormant" in tiers["dormant"], tiers["dormant"]
    assert B + "dormant" not in tiers["rising"]
    print("✓ classification + dormant 0→1-click guard")


def test_audit_report():
    fb = classifier.classify(gsc=_sample_gsc(), inventory=_sample_inventory())
    md = audit.build_report(fb)
    assert "Performance Audit" in md
    assert "Winners" in md and "Decaying" in md
    assert "+39%" in md  # domain clicks trend
    # empty-GSC path produces the credentials warning, not a normal report
    empty = audit.build_report(classifier.classify(gsc={}, inventory={}))
    assert "No GSC performance data" in empty
    print("✓ audit report rendering (+ empty-GSC warning path)")


def test_scorer_wiring():
    fb = classifier.classify(gsc=_sample_gsc(), inventory=_sample_inventory())
    classifier.load_feedback = lambda: fb          # inject feedback, no disk
    scored = scorer.score(research={}, inventory=_sample_inventory())
    perf = [c for c in scored["candidates"] if c["source"].startswith("performance")]
    winners = [c for c in perf if c["source"] == "performance_winner"]
    refresh = [c for c in perf if c["source"] == "performance_refresh"]
    assert winners, "expected scale_winner candidates"
    assert refresh, "expected refresh candidates"
    assert all(c["recommended_action"] == "create_new_article" for c in winners)
    assert all(c["recommended_action"] == "update_existing_article" for c in refresh)
    # momentum boost: a winner should outrank a plain decayer refresh
    assert max(c["opportunity_score"] for c in winners) >= max(c["opportunity_score"] for c in refresh)
    print("✓ scorer turns feedback into scored scale/refresh candidates")


if __name__ == "__main__":
    test_classification()
    test_audit_report()
    test_scorer_wiring()
    print("\nALL PHASE-5 TESTS PASSED")
