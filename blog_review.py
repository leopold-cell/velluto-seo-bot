#!/usr/bin/env python3
"""
Velluto SEO — 28-Day Blog Review + Site SEO/GEO Audit
=====================================================
Reviews ALL published blog posts every 28 days:
  1. Quality          (briefs/quality_gate checks + Claude score)
  2. Performance       (GSC per-page clicks/impressions/position, 28d)
  3. Translations      (completeness across 10 locales; safe auto-fix of missing)
  4. UI                (Playwright screenshots → Claude vision, mobile + desktop)
  5. Site SEO + GEO    (technical on-page + generative-engine readiness)

Delivery: WhatsApp (Meta Cloud API) with Telegram fallback; full report committed
under output/blog_review/.

Runs from the VPS cron (run.sh) daily but SELF-GATES to every `interval_days`
(28) via output/blog_review/state.json — cron can't express a true 28-day cycle.

Usage:
  python3 blog_review.py                # gated: runs only if ≥28 days since last
  python3 blog_review.py --force        # run now regardless of gate
  python3 blog_review.py --dry-run      # no writes / sends / auto-fixes
  python3 blog_review.py --skip-ui      # skip the Playwright/vision step
  python3 blog_review.py --no-autofix   # report missing translations, don't fix
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
import traceback

from review import (_common, inventory, quality_audit, performance_audit,
                    translation_audit, ui_audit, seo_geo_audit, report as report_mod,
                    whatsapp)


def _gate_ok(force: bool) -> tuple[bool, str]:
    if force:
        return True, "forced"
    cfg = _common.review_config()
    interval = cfg["interval_days"]
    state = _common.load_state()
    last = state.get("last_run")
    if not last:
        return True, "no previous run"
    try:
        last_date = _dt.date.fromisoformat(last)
    except Exception:
        return True, "unparseable state"
    elapsed = (_common.today() - last_date).days
    if elapsed >= interval:
        return True, f"{elapsed}d since last run (≥{interval})"
    return False, f"only {elapsed}d since last run (<{interval})"


def run(force=False, dry_run=False, skip_ui=False, autofix=True) -> dict | None:
    ok, why = _gate_ok(force)
    print(f"🗓️  28-day gate: {'RUN' if ok else 'SKIP'} — {why}")
    if not ok:
        return None

    deep = _common.have_anthropic()

    # 1. Inventory
    all_articles = inventory.fetch_all_articles()
    bot_articles = [a for a in all_articles if inventory.is_bot_article(a)]
    inv_summary = {"total_articles": len(all_articles), "bot_articles": len(bot_articles)}
    print(f"📚 Inventory: {len(bot_articles)} bot articles (of {len(all_articles)})")

    # 2. Quality
    print("🔎 Quality audit…")
    quality = quality_audit.audit(bot_articles, deep=deep)

    # 3. Performance (refresh per-page GSC first)
    print("📈 Performance audit…")
    if not dry_run:
        performance_audit.refresh_gsc_performance()
    performance = performance_audit.audit(bot_articles)

    # 4. Translations (+ safe auto-fix of missing locales)
    print("🌍 Translation audit…")
    translations = translation_audit.audit(bot_articles, deep=False)
    autofix_result = None
    if autofix and not dry_run and translations.get("articles_needing_fix"):
        print("   🔧 Auto-fixing missing translations…")
        autofix_result = translation_audit.autofix_missing(translations["results"])

    # 5. UI
    if skip_ui:
        ui = {"skipped": True, "reason": "--skip-ui"}
    else:
        print("🖥️  UI audit (screenshots + vision)…")
        ui = ui_audit.audit(bot_articles)

    # 6. Site SEO + GEO
    print("🧭 SEO + GEO audit…")
    seo_geo = seo_geo_audit.audit(bot_articles)

    # Aggregate
    report = report_mod.build(inv_summary, quality, performance, translations,
                              ui, seo_geo, autofix_result)

    if dry_run:
        print("🧪 DRY RUN — not writing/sending. Markdown preview:\n")
        print(report_mod.to_markdown(report))
        return report

    json_path, md_path = report_mod.persist(report)
    print(f"💾 Saved {json_path}")
    channel = whatsapp.deliver(report_mod.to_whatsapp(report))
    print(f"📨 Report delivered via: {channel}")

    state = _common.load_state()
    state["last_run"] = _common.today().isoformat()
    state.setdefault("history", []).append(report["review_date"])
    state["history"] = state["history"][-24:]
    _common.save_state(state)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-ui", action="store_true")
    ap.add_argument("--no-autofix", action="store_true")
    args = ap.parse_args()
    try:
        run(force=args.force, dry_run=args.dry_run, skip_ui=args.skip_ui,
            autofix=not args.no_autofix)
    except Exception as e:
        tb = traceback.format_exc().splitlines()
        msg = (f"❌ Velluto Blog Review FAILED {_dt.date.today()}\n"
               f"{type(e).__name__}: {str(e)[:180]}")
        print(msg)
        print("\n".join(tb[-6:]))
        try:
            whatsapp.deliver(msg)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
