"""
28-day performance audit (Phase 5).

Every 28 days, turn the performance feedback into a Claude-readable markdown
report in output/ — the file you (or Claude Code) open when working interactively
to see what's winning, what's slipping, and exactly what to scale next.

Cadence is self-gating via data/processed/last_performance_audit.json so it fires
~once every 28 days inside the daily VPS run. Also runnable on demand:
    python -m performance.audit --force
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys

from performance import classifier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH  = os.path.join(ROOT, "data", "processed", "last_performance_audit.json")
REPORT_DIR  = os.path.join(ROOT, "output")
INTERVAL_DAYS = 28


def _last_audit_date() -> _dt.date | None:
    if not os.path.exists(STATE_PATH):
        return None
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return _dt.date.fromisoformat(json.load(f)["date"])
    except Exception:
        return None


def due(today: _dt.date | None = None) -> bool:
    today = today or _dt.date.today()
    last = _last_audit_date()
    return last is None or (today - last).days >= INTERVAL_DAYS


def _mark_done(today: _dt.date, report_path: str) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"date": today.isoformat(), "report": report_path}, f, indent=2)


def _fmt_pct(v) -> str:
    try:
        return f"{float(v):+.0f}%"
    except Exception:
        return "n/a"


def _row(r: dict) -> str:
    name = r.get("title") or r.get("url", "").replace(classifier.BLOG_PREFIX, ".../")
    return (f"| {name[:60]} | {r.get('curr_clicks',0)} | "
            f"{_fmt_pct(r.get('clicks_delta_pct'))} | {r.get('curr_impressions',0)} |")


def build_report(feedback: dict) -> str:
    today = feedback.get("date", _dt.date.today().isoformat())
    c = feedback.get("counts", {})
    t = feedback.get("totals", {})
    tiers = feedback.get("tiers", {})

    if not feedback.get("gsc_available"):
        return (f"# Velluto SEO — Performance Audit ({today})\n\n"
                "⚠️ No GSC performance data was available (gsc_performance.json empty).\n\n"
                "Check that `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN` are set on the VPS and that "
                "`GSC_SITE_URL` matches the verified Search Console property "
                "(`sc-domain:velluto-shop.com` for a Domain property).\n")

    L: list[str] = []
    L.append(f"# Velluto SEO — Performance Audit ({today})")
    L.append("")
    L.append(f"_28-day window {feedback.get('windows', {}).get('current', '?')} "
             f"vs previous {feedback.get('windows', {}).get('previous', '?')}._")
    L.append("")
    L.append("## Domain trend")
    L.append("")
    L.append(f"- Clicks: **{t.get('curr_clicks', 0)}** ({_fmt_pct(t.get('clicks_delta_pct'))} vs prev)")
    L.append(f"- Impressions: **{t.get('curr_impressions', 0)}** ({_fmt_pct(t.get('impr_delta_pct'))} vs prev)")
    L.append(f"- Pages evaluated: {c.get('pages_evaluated', 0)} — "
             f"{c.get('winner',0)} winners · {c.get('rising',0)} rising · "
             f"{c.get('decaying',0)} decaying · {c.get('dormant',0)} dormant · {c.get('steady',0)} steady")
    L.append("")

    # WINNERS → scale
    L.append("## 🏆 Winners — scale these (cluster + internal links)")
    L.append("")
    if tiers.get("winner"):
        L.append("| Page | Clicks | Δ Clicks | Impr |")
        L.append("|---|---|---|---|")
        for r in tiers["winner"][:10]:
            L.append(_row(r))
        L.append("")
        L.append("**How to scale:** for each winner, publish 1–3 supporting articles "
                 "targeting its striking-distance queries and add internal links from the "
                 "new pieces back to the winner. The bot will auto-create these as "
                 "`scale_winner` candidates.")
        L.append("")
        for r in tiers["winner"][:5]:
            if r.get("top_queries"):
                qs = ", ".join(q["query"] for q in r["top_queries"] if q.get("query"))
                L.append(f"- **{(r.get('title') or r['url'])[:60]}** → cluster around: {qs}")
        L.append("")
    else:
        L.append("_No clear winners yet — the catalogue is still young. Focus on rising pages._")
        L.append("")

    # RISING → nurture
    L.append("## 📈 Rising — nurture (about to break out)")
    L.append("")
    if tiers.get("rising"):
        L.append("| Page | Clicks | Δ Clicks | Impr |")
        L.append("|---|---|---|---|")
        for r in tiers["rising"][:10]:
            L.append(_row(r))
        L.append("")
    else:
        L.append("_None this period._")
        L.append("")

    # DECAYING → refresh
    L.append("## 📉 Decaying — refresh now")
    L.append("")
    if tiers.get("decaying"):
        L.append("| Page | Clicks | Δ Clicks | Impr |")
        L.append("|---|---|---|---|")
        for r in tiers["decaying"][:10]:
            L.append(_row(r))
        L.append("")
        L.append("**Action:** queued as `update_existing_article` (refresh intro, freshen data, "
                 "re-target intent, strengthen internal links).")
        L.append("")
    else:
        L.append("_Nothing decaying — traffic is holding._")
        L.append("")

    # DORMANT → CTR fix
    L.append("## 😴 Dormant — high impressions, ~no clicks (fix CTR/intent)")
    L.append("")
    if tiers.get("dormant"):
        L.append("| Page | Clicks | Δ Clicks | Impr |")
        L.append("|---|---|---|---|")
        for r in tiers["dormant"][:10]:
            L.append(_row(r))
        L.append("")
        L.append("**Action:** rewrite title/meta to match intent; the page is seen but not chosen.")
        L.append("")
    else:
        L.append("_None this period._")
        L.append("")

    L.append("---")
    L.append(f"_Generated by performance/audit.py · next audit in ~{INTERVAL_DAYS} days._")
    L.append("")
    return "\n".join(L)


def write_report(feedback: dict) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    today = feedback.get("date", _dt.date.today().isoformat())
    path = os.path.join(REPORT_DIR, f"performance_audit_{today}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_report(feedback))
    # Stable "latest" pointer Claude Code can always open
    latest = os.path.join(REPORT_DIR, "performance_audit_latest.md")
    with open(latest, "w", encoding="utf-8") as f:
        f.write(build_report(feedback))
    return path


def maybe_run(force: bool = False, feedback: dict | None = None) -> dict:
    """Run the audit if due (or forced). Safe to call every day."""
    today = _dt.date.today()
    if not force and not due(today):
        last = _last_audit_date()
        days = (today - last).days if last else 0
        return {"ran": False, "reason": f"not due (last {days}d ago, interval {INTERVAL_DAYS}d)"}
    fb = feedback if feedback is not None else classifier.run()
    path = write_report(fb)
    _mark_done(today, path)
    return {"ran": True, "path": path, "counts": fb.get("counts", {})}


if __name__ == "__main__":
    force = "--force" in sys.argv
    res = maybe_run(force=force)
    print(json.dumps(res, indent=2, ensure_ascii=False))
