#!/usr/bin/env python3
"""
Daily Anthropic API cost watchdog — real billing data, not estimates.

Why: the July cost spike ($126 MTD, ~$60-75 of it one-off retrofit/rewrite runs)
was invisible to the bot because the internal token logger (seo_bot.log_usage)
only covers 4 modules; the expensive paths (11-locale re-adaptations, retrofit,
legal rewrite) never logged. This monitor pulls the ORGANIZATION's actual cost
from the Anthropic Usage & Cost Admin API instead, so nothing can burn silently.

  GET https://api.anthropic.com/v1/organizations/cost_report
  Amounts arrive as decimal strings in CENTS (USD); daily buckets; data is
  fresh ~5 minutes after each request. Requires an ADMIN key (sk-ant-admin01-…),
  which is NOT the normal API key: Console → Settings → Organization → Admin keys.

Behavior (runs daily via run.sh; every failure is soft — never breaks the chain):
  1. Fetch month-to-date daily cost, grouped by description (→ per-model split).
  2. Persist to data/api_cost_history.json (committed by the daily cron).
  3. Print a one-line summary: yesterday / 7-day avg / month-to-date.
  4. Email a warning when yesterday > API_COST_WARN_DAILY_USD (default 8) or
     MTD > API_COST_WARN_MONTHLY_USD (default 120) — thresholds via .env.

No admin key set → prints the setup hint and exits cleanly (no-op).
Manual: python3 scripts/api_cost_monitor.py
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from decimal import Decimal

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, ".env"), override=True)

ADMIN_KEY   = os.getenv("ANTHROPIC_ADMIN_KEY", "")
API         = "https://api.anthropic.com/v1/organizations/cost_report"
HISTORY     = os.path.join(BASE, "data", "api_cost_history.json")
WARN_DAILY  = float(os.getenv("API_COST_WARN_DAILY_USD", "8"))
WARN_MONTH  = float(os.getenv("API_COST_WARN_MONTHLY_USD", "120"))


def _fetch_month() -> dict[str, dict]:
    """{'YYYY-MM-DD': {'total': usd float, 'by_model': {model: usd}}} for MTD."""
    today = datetime.date.today()
    start = today.replace(day=1)
    params = {
        "starting_at": f"{start.isoformat()}T00:00:00Z",
        "ending_at":   f"{(today + datetime.timedelta(days=1)).isoformat()}T00:00:00Z",
        "group_by[]":  "description",
        "limit":       31,
    }
    headers = {"x-api-key": ADMIN_KEY, "anthropic-version": "2023-06-01"}
    out: dict[str, dict] = {}
    page = None
    for _ in range(10):  # pagination safety bound
        if page:
            params["page"] = page
        r = requests.get(API, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        d = r.json()
        for bucket in d.get("data", []):
            day = str(bucket.get("starting_at", ""))[:10]
            e = out.setdefault(day, {"total": Decimal(0), "by_model": {}})
            for res in bucket.get("results", []):
                # amounts are decimal strings in CENTS
                usd = Decimal(str(res.get("amount", "0"))) / 100
                e["total"] += usd
                model = res.get("model") or res.get("description") or "other"
                e["by_model"][model] = e["by_model"].get(model, Decimal(0)) + usd
        if not d.get("has_more"):
            break
        page = d.get("next_page")
        if not page:
            break
    # Decimal → float for JSON
    return {day: {"total": round(float(e["total"]), 4),
                  "by_model": {m: round(float(v), 4) for m, v in e["by_model"].items()}}
            for day, e in out.items()}


def main() -> None:
    today = datetime.date.today()
    print(f"\n💰 API Cost Monitor — {today}")
    if not ADMIN_KEY:
        print("   · ANTHROPIC_ADMIN_KEY not set — skipping (real-billing watchdog inactive).")
        print("     Setup: Console → Settings → Organization → Admin keys → create key")
        print("     (sk-ant-admin01-…) → add ANTHROPIC_ADMIN_KEY=… to .env")
        return

    try:
        month = _fetch_month()
    except Exception as e:
        print(f"   ⚠️  cost_report fetch failed: {e} — skipping")
        return

    mtd = round(sum(d["total"] for d in month.values()), 2)
    yesterday = (today - datetime.timedelta(days=1)).isoformat()
    y_cost = round(month.get(yesterday, {}).get("total", 0.0), 2)
    last7 = sorted(month.keys())[-7:]
    avg7 = round(sum(month[d]["total"] for d in last7) / max(1, len(last7)), 2)
    print(f"   Gestern: ${y_cost} | 7-Tage-Schnitt: ${avg7}/Tag | Monat: ${mtd} "
          f"(Warnschwellen: ${WARN_DAILY}/Tag, ${WARN_MONTH}/Monat)")

    # persist (committed by the daily cron → history survives re-clones)
    try:
        os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
        hist = {}
        if os.path.exists(HISTORY):
            try:
                hist = json.load(open(HISTORY, encoding="utf-8"))
            except Exception:
                hist = {}
        hist.update(month)
        json.dump(hist, open(HISTORY, "w", encoding="utf-8"), indent=1, sort_keys=True)
    except Exception as e:
        print(f"   ⚠️  history write failed: {e}")

    warnings = []
    if y_cost > WARN_DAILY:
        warnings.append(f"Tageskosten gestern ({yesterday}): ${y_cost} > ${WARN_DAILY} Warnschwelle")
    if mtd > WARN_MONTH:
        warnings.append(f"Monatskosten (MTD): ${mtd} > ${WARN_MONTH} Warnschwelle")
    if not warnings:
        print("   ✓ innerhalb der Schwellen")
        return

    top = sorted(month.get(yesterday, {}).get("by_model", {}).items(),
                 key=lambda kv: kv[1], reverse=True)[:5]
    breakdown = "\n".join(f"  - {m}: ${v}" for m, v in top) or "  (keine Detail-Daten)"
    trend = "\n".join(f"  {d}: ${month[d]['total']:.2f}" for d in sorted(month)[-7:])
    body = ("⚠️ Die Anthropic-API-Kosten des SEO-Bots liegen über der Warnschwelle.\n\n"
            + "\n".join(f"• {w}" for w in warnings)
            + f"\n\nKosten gestern nach Modell/Posten:\n{breakdown}"
            + f"\n\nLetzte 7 Tage:\n{trend}"
            + "\n\nSchwellen anpassen: API_COST_WARN_DAILY_USD / API_COST_WARN_MONTHLY_USD in .env."
            + "\nDetails: https://console.anthropic.com → Cost")
    print("   🚨 " + " | ".join(warnings))
    try:
        import mailer
        mailer.send_email(f"💸 SEO-Bot API-Kosten-Warnung — {today}", body)
        print("   ✉️  Warn-Mail verschickt")
    except Exception as e:
        print(f"   ⚠️  Warn-Mail fehlgeschlagen: {e}")


if __name__ == "__main__":
    main()
