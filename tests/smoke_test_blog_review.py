"""
Smoke test for the 28-day blog review (offline, no credentials).

Verifies: the 28-day gate, performance bucketing, translation completeness,
deterministic quality checks, UI target selection, and report rendering.

Run: python3 tests/smoke_test_blog_review.py
"""
import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from review import (_common, quality_audit, performance_audit,
                    translation_audit, ui_audit, seo_geo_audit, report as report_mod)
import blog_review

failures = []


def check(name, cond):
    print(("✅" if cond else "❌") + f" {name}")
    if not cond:
        failures.append(name)


# ── 1. 28-day gate ──────────────────────────────────────────────────────────
_orig_load = _common.load_state
_common.load_state = lambda: {}                       # no previous run
check("gate: no state → run", blog_review._gate_ok(False)[0] is True)

_common.load_state = lambda: {"last_run": _dt.date.today().isoformat()}
check("gate: today → skip", blog_review._gate_ok(False)[0] is False)

old = (_dt.date.today() - _dt.timedelta(days=40)).isoformat()
_common.load_state = lambda: {"last_run": old}
check("gate: 40d ago → run", blog_review._gate_ok(False)[0] is True)
check("gate: --force overrides", blog_review._gate_ok(True)[0] is True)
_common.load_state = _orig_load

# ── 2. performance bucketing (fixture) ──────────────────────────────────────
performance_audit._load_performance = lambda: {
    "windows": {"current": ["2026-05-20", "2026-06-17"]},
    "totals": {"curr_clicks": 100},
    "per_page_deltas": [
        {"page": "https://velluto-shop.com/blogs/velluto-the-magazine/a", "curr_impressions": 5, "curr_clicks": 0},
        {"page": "https://velluto-shop.com/blogs/velluto-the-magazine/b", "curr_impressions": 40, "curr_clicks": 1},
        {"page": "https://velluto-shop.com/blogs/velluto-the-magazine/c", "curr_impressions": 500, "curr_clicks": 60},
    ],
    "low_ctr_pages": [],
}
arts = [
    {"handle": "a", "url": "https://velluto-shop.com/blogs/velluto-the-magazine/a", "published_at": "2026-06-01"},
    {"handle": "b", "url": "https://velluto-shop.com/blogs/velluto-the-magazine/b", "published_at": "2026-06-01"},
    {"handle": "c", "url": "https://velluto-shop.com/blogs/velluto-the-magazine/c", "published_at": "2026-06-01"},
    {"handle": "d", "url": "https://velluto-shop.com/blogs/velluto-the-magazine/d", "published_at": "2026-06-01"},
]
perf = performance_audit.audit(arts)
check("perf: a=dead", perf["buckets"]["dead"] == 1)
check("perf: b=weak", perf["buckets"]["weak"] == 1)
check("perf: c=performing", perf["buckets"]["performing"] == 1)
check("perf: d=no_data", perf["buckets"]["no_data"] == 1)

# ── 3. translation completeness ─────────────────────────────────────────────
translation_audit.registered_locales = lambda aid: {"de", "nl"} if aid == 1 else set(_common.SHOP_LOCALES)
tarts = [{"id": 1, "handle": "a"}, {"id": 2, "handle": "b"}]
tr = translation_audit.audit(tarts)
check("trans: 1 fully complete", tr["fully_complete"] == 1)
check("trans: article 1 needs fix", 1 in tr["articles_needing_fix"])
check("trans: missing locales reported", "fr" in tr["missing_by_locale"])

# ── 4. deterministic quality checks ─────────────────────────────────────────
bad = {"id": 9, "handle": "x", "title": "Short", "body_html": '<p class="vl">tiny</p>',
       "summary_html": "", "word_count": 1, "tags": ["cycling glasses"]}
qr = quality_audit.audit_article(bad, deep=False)
check("quality: flags short article", len(qr["deterministic_issues"]) > 0)

# ── 5. UI target selection (offline, deterministic) ─────────────────────────
recent_day = (_dt.date.today() - _dt.timedelta(days=3)).isoformat()
old_day = (_dt.date.today() - _dt.timedelta(days=200)).isoformat()
ui_arts = [{"handle": f"h{i}", "url": f"u{i}", "published_at": old_day,
            "body_html": "<p>x</p>"} for i in range(10)]
ui_arts[0]["published_at"] = recent_day                       # recent → always included
ui_arts[1]["body_html"] = "<img><img><img><img><img><img>"     # heuristic flag
targets = ui_audit.select_targets(ui_arts)
check("ui: recent post selected", any(t["handle"] == "h0" for t in targets))
check("ui: image-heavy post selected", any(t["handle"] == "h1" for t in targets))

# ── 6. report rendering (no exceptions, contains sections) ──────────────────
rep = report_mod.build(
    {"total_articles": 4, "bot_articles": 3},
    {"avg_llm_score": 72, "with_issues": 1, "weak": 0, "articles_checked": 3},
    perf, tr, {"skipped": True, "reason": "--skip-ui"},
    {"technical_issues": ["home: no canonical tag"], "geo": {"seo_score": 80, "geo_score": 65,
                                                            "top_seo_fixes": ["x"], "top_geo_gaps": ["y"]}},
    None)
md = report_mod.to_markdown(rep)
wa = report_mod.to_whatsapp(rep)
check("report: markdown has all 5 sections",
      all(s in md for s in ["## 1. Quality", "## 2. Performance", "## 3. Translations",
                            "## 4. UI", "## 5. Site SEO + GEO"]))
check("report: whatsapp summary non-empty", len(wa) > 30 and "Velluto" in wa)

print("\n" + ("🎉 ALL PASSED" if not failures else f"💥 FAILED: {failures}"))
sys.exit(1 if failures else 0)
