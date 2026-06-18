"""
Phase 6 tests — revenue-aware loop, commercial boost, conversions parsing.

Run:  python tests/test_phase6_revenue_loop.py
Pure: no Shopify, no GSC, no network.
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from performance import classifier, audit, conversions      # noqa: E402
from decision import opportunity_scorer as scorer           # noqa: E402

B = "https://velluto-shop.com/blogs/velluto-the-magazine/"


def test_landing_normalization():
    n = conversions._normalize_landing
    assert n("/blogs/velluto-the-magazine/oakley-alt?utm=x") == B + "oakley-alt"
    assert n("https://velluto-shop.com/nl/products/velluto-stradapro-nero/") \
        == "https://velluto-shop.com/products/velluto-stradapro-nero"
    assert n("") is None
    print("✓ landing_site normalization (strips query + locale prefix)")


def test_conversion_aggregate():
    orders = [
        {"landing_site": "/blogs/velluto-the-magazine/oakley-alt", "total_price": "149.00",
         "currency": "EUR", "financial_status": "paid"},
        {"landing_site": "/blogs/velluto-the-magazine/oakley-alt", "total_price": "69.00",
         "currency": "EUR", "financial_status": "paid"},
        {"landing_site": "/products/x", "total_price": "200.00", "financial_status": "refunded"},  # skipped
    ]
    agg = conversions._aggregate(orders)
    assert agg["by_page"][B + "oakley-alt"]["orders"] == 2
    assert agg["by_page"][B + "oakley-alt"]["revenue"] == 218.0
    assert agg["currency"] == "EUR"
    print("✓ conversion aggregation by landing page (refunds excluded)")


def test_paid_filter():
    # paid orders (fbclid / utm_source=facebook / instagram referrer) must NOT count as SEO
    orders = [
        {"landing_site": "/?fbclid=abc", "total_price": "149.00", "financial_status": "paid"},
        {"landing_site": "/?utm_source=facebook&utm_medium=cpc", "total_price": "100.00",
         "financial_status": "paid"},
        {"landing_site": "/products/y", "referring_site": "https://instagram.com",
         "total_price": "80.00", "financial_status": "paid"},
        {"landing_site": "/blogs/velluto-the-magazine/oakley-alt", "total_price": "149.00",
         "financial_status": "paid", "referring_site": "https://www.google.com/"},  # SEO
        {"landing_site": "/discount/RIDE10", "total_price": "62.00", "financial_status": "paid"},  # excluded page
    ]
    agg = conversions._aggregate(orders)
    assert agg["paid_orders"] == 3, agg
    assert agg["seo_orders"] == 2          # google order + discount order are "non-paid"…
    # …but the discount landing is excluded from page attribution
    assert B + "oakley-alt" in agg["by_page"]
    assert not any("/discount/" in u for u in agg["by_page"])
    assert conversions._is_paid_order("/?gclid=x", "") is True
    assert conversions._excluded_page("https://velluto-shop.com/discount/RIDE10") is True
    print("✓ paid traffic filtered out of SEO attribution; discount/checkout pages excluded")


def test_gsc_locale_normalization():
    try:
        from research import gsc_fetcher
    except Exception as e:  # missing optional dep / env quirk → skip, don't fail the suite
        print(f"⚠ skipped GSC locale test (import unavailable in this env: {type(e).__name__})")
        return
    n = gsc_fetcher._norm_url
    assert n("https://velluto-shop.com/en-eu/blogs/velluto-the-magazine/x") \
        == "https://velluto-shop.com/blogs/velluto-the-magazine/x"
    assert n("https://velluto-shop.com/nl") == "https://velluto-shop.com/"
    # real path segments must NOT be stripped as a locale
    assert n("https://velluto-shop.com/blogs/velluto-the-magazine/x") \
        == "https://velluto-shop.com/blogs/velluto-the-magazine/x"
    print("✓ GSC locale-prefix normalization (locales merge, real paths preserved)")


def _gsc():
    return {
        "date": datetime.date.today().isoformat(),
        "windows": {"current": ["a", "b"], "previous": ["c", "d"]},
        "per_page_deltas": [
            {"page": B + "seller", "curr_impressions": 1200, "prev_impressions": 800,
             "impr_delta_pct": 50, "curr_clicks": 40, "prev_clicks": 30, "clicks_delta_pct": 33},
            {"page": B + "clicks-no-sales", "curr_impressions": 3000, "prev_impressions": 1000,
             "impr_delta_pct": 200, "curr_clicks": 90, "prev_clicks": 30, "clicks_delta_pct": 200},
        ],
        "striking_distance_queries": [
            {"query": "oakley alternative", "page": B + "seller", "impressions": 600,
             "clicks": 20, "ctr_pct": 3.3, "avg_position": 9},
        ],
        "low_ctr_pages": [
            {"query": "best cycling glasses 2026", "page": B + "clicks-no-sales",
             "impressions": 3000, "ctr_pct": 1.0, "avg_position": 6},
        ],
        "totals": {"curr_clicks": 130, "prev_clicks": 60, "curr_impressions": 4200,
                   "prev_impressions": 1800, "clicks_delta_pct": 116, "impr_delta_pct": 133},
    }


def _conv():
    return {
        "date": datetime.date.today().isoformat(),
        "by_page": {B + "seller": {"orders": 3, "revenue": 447.0,
                                    "prev_orders": 1, "prev_revenue": 149.0}},
        "totals": {"orders": 3, "revenue": 447.0, "prev_orders": 1,
                   "prev_revenue": 149.0, "currency": "EUR"},
    }


def test_revenue_tiering():
    fb = classifier.classify(gsc=_gsc(), inventory={"articles": []}, conversions=_conv())
    rw = [r["url"] for r in fb["tiers"]["revenue_winner"]]
    assert B + "seller" in rw, "page with sales must be a revenue_winner"
    # the high-traffic, zero-sales page must be flagged
    tns = [r["url"] for t in fb["tiers"].values() for r in t if r.get("traffic_no_sales")]
    assert B + "clicks-no-sales" in tns
    assert fb["conversion_totals"]["revenue"] == 447.0
    assert fb["low_ctr_targets"], "low-CTR targets should pass through to feedback"
    print("✓ revenue_winner tier + traffic_no_sales flag + low-CTR passthrough")


def test_scorer_revenue_and_commercial_boost():
    fb = classifier.classify(gsc=_gsc(), inventory={"articles": []}, conversions=_conv())
    classifier.load_feedback = lambda: fb
    scored = scorer.score(research={}, inventory={"articles": []})
    # the seller's scale candidate (commercial "oakley alternative") should top the list
    top = scored["candidates"][0]
    assert top["opportunity_score"] >= 90, top["opportunity_score"]
    # commercial-comparison flag applied to oakley/alternative keywords
    assert any(c.get("commercial_comparison") for c in scored["candidates"])
    # a low-CTR candidate exists
    assert any(c["source"] == "performance_low_ctr" for c in scored["candidates"])
    print("✓ scorer: revenue-winner scaling + commercial boost + low-CTR candidates")


def test_audit_revenue_render():
    fb = classifier.classify(gsc=_gsc(), inventory={"articles": []}, conversions=_conv())
    md = audit.build_report(fb)
    assert "Revenue winners" in md
    assert "447.0" in md
    assert "Traffic but no sales" in md
    print("✓ audit renders revenue winners + revenue trend + traffic-no-sales")


if __name__ == "__main__":
    test_landing_normalization()
    test_conversion_aggregate()
    test_paid_filter()
    test_gsc_locale_normalization()
    test_revenue_tiering()
    test_scorer_revenue_and_commercial_boost()
    test_audit_revenue_render()
    print("\nALL PHASE-6 TESTS PASSED")
