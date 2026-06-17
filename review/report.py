"""
Aggregate the five audits into a single report: full JSON, a human-readable
Markdown summary, and a compact WhatsApp/Telegram message.
"""
from __future__ import annotations

import datetime as _dt
import os

from review._common import REVIEW_DIR, write_json


def build(inventory_summary: dict, quality: dict, performance: dict,
          translations: dict, ui: dict, seo_geo: dict, autofix: dict | None) -> dict:
    return {
        "review_date": _dt.date.today().isoformat(),
        "inventory": inventory_summary,
        "quality": quality,
        "performance": performance,
        "translations": translations,
        "ui": ui,
        "seo_geo": seo_geo,
        "autofix": autofix or {},
    }


def _g(d: dict, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, {})
    return d if d != {} else default


def to_markdown(report: dict) -> str:
    q, p, t, u, s = (report["quality"], report["performance"],
                     report["translations"], report["ui"], report["seo_geo"])
    lines = [
        f"# Velluto 28-Day Blog Review — {report['review_date']}",
        "",
        f"**Articles reviewed:** {report['inventory'].get('bot_articles', 0)} "
        f"(of {report['inventory'].get('total_articles', 0)} total)",
        "",
        "## 1. Quality",
        f"- Avg LLM score: {q.get('avg_llm_score')}",
        f"- With deterministic issues: {q.get('with_issues')}",
        f"- Weak (LLM verdict): {q.get('weak')}",
        "",
        "## 2. Performance (GSC, 28d)",
    ]
    if p.get("has_gsc_data"):
        b = p.get("buckets", {})
        lines += [
            f"- Window: {p.get('window')}",
            f"- Dead: {b.get('dead',0)} · Weak: {b.get('weak',0)} · "
            f"Low-CTR: {b.get('low_ctr',0)} · Performing: {b.get('performing',0)} · "
            f"No data: {b.get('no_data',0)}",
        ]
    else:
        lines.append("- ⚠️ No GSC data available (credentials missing or fetch failed).")
    lines += [
        "",
        "## 3. Translations",
        f"- Fully complete: {t.get('fully_complete')}/{t.get('articles_checked')}",
        f"- Avg completeness: {t.get('avg_completeness_pct')}%",
        f"- Missing locales: {', '.join(t.get('missing_by_locale', {}).keys()) or 'none'}",
    ]
    if report.get("autofix") and not report["autofix"].get("skipped"):
        lines.append(f"- Auto-fixed: {len(report['autofix'].get('fixed', []))} locale(s)")
    lines += ["", "## 4. UI (mobile + desktop)"]
    if u.get("skipped"):
        lines.append(f"- ⚠️ Skipped: {u.get('reason')}")
    else:
        lines.append(f"- Checked {u.get('targets',0)} · broken: {u.get('broken',0)} · minor: {u.get('minor',0)}")
        for r in u.get("results", []):
            if r.get("verdict") in ("broken", "minor"):
                issues = (r.get("mobile_issues") or []) + (r.get("desktop_issues") or [])
                lines.append(f"  - {r.get('handle')}: {r.get('verdict')} — {'; '.join(issues[:3])}")
    lines += ["", "## 5. Site SEO + GEO"]
    geo = s.get("geo") or {}
    if geo:
        lines += [
            f"- SEO score: {geo.get('seo_score')} · GEO score: {geo.get('geo_score')}",
            f"- Top SEO fixes: {'; '.join((geo.get('top_seo_fixes') or [])[:3])}",
            f"- Top GEO gaps: {'; '.join((geo.get('top_geo_gaps') or [])[:3])}",
        ]
    for iss in (s.get("technical_issues") or [])[:8]:
        lines.append(f"- ⚙️ {iss}")
    return "\n".join(lines)


def to_whatsapp(report: dict) -> str:
    q, p, t, u, s = (report["quality"], report["performance"],
                     report["translations"], report["ui"], report["seo_geo"])
    b = p.get("buckets", {})
    geo = s.get("geo") or {}
    parts = [
        f"📋 Velluto 28-Day Blog Review ({report['review_date']})",
        f"Posts: {report['inventory'].get('bot_articles', 0)}",
        f"Quality: avg {q.get('avg_llm_score')}, {q.get('with_issues')} w/ issues, {q.get('weak')} weak",
    ]
    if p.get("has_gsc_data"):
        parts.append(f"GSC: {b.get('dead',0)} dead, {b.get('weak',0)} weak, {b.get('performing',0)} performing")
    else:
        parts.append("GSC: no data")
    parts.append(f"Translations: {t.get('fully_complete')}/{t.get('articles_checked')} complete"
                 + (f", fixed {len(report.get('autofix',{}).get('fixed',[]))}" if report.get('autofix', {}).get('fixed') else ""))
    if u.get("skipped"):
        parts.append("UI: skipped")
    else:
        parts.append(f"UI: {u.get('broken',0)} broken, {u.get('minor',0)} minor")
    if geo:
        parts.append(f"SEO {geo.get('seo_score')} / GEO {geo.get('geo_score')}")
    parts.append("Full report committed to repo: output/blog_review/")
    return "\n".join(parts)


def persist(report: dict) -> tuple[str, str]:
    """Write <date>.json + latest.md. Returns (json_path, md_path)."""
    date = report["review_date"]
    json_path = os.path.join(REVIEW_DIR, f"{date}.json")
    md_path = os.path.join(REVIEW_DIR, "latest.md")
    write_json(json_path, report)
    os.makedirs(REVIEW_DIR, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(report))
    return json_path, md_path
