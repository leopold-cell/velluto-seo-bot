#!/usr/bin/env python3
"""
Weekly Meta Ads performance report — READ-ONLY.

Pulls campaign-level insights (spend, clicks, CTR, CPC, purchases, revenue,
ROAS) for the last COMPLETED ISO week (Mon-Sun), compares week-over-week,
appends to data/meta_ads_history.json (committed by the daily cron → the
trend feeds the dashboard's Meta Ads section) and sends an email summary.

Self-gating: runs as a normal step in the daily run.sh. It only does work
when the last completed week is not in the history yet — i.e. effectively
every Monday, and it self-heals if that run failed (fires the next day).

ENV: META_ACCESS_TOKEN (ads_read), META_AD_ACCOUNT_ID (act_…),
     EMAIL_FROM + EMAIL_APP_PASS (optional, for the summary email).

Usage:
  python3 scripts/meta_ads_report.py            # gated (last completed week)
  python3 scripts/meta_ads_report.py --force    # re-fetch + resend last week
  python3 scripts/meta_ads_report.py --week 2026-06-29   # specific week start
"""
import datetime as dt
import json
import os
import sys

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"), override=True)

META_ACCESS_TOKEN  = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")
GRAPH_VERSION = "v22.0"  # keep in sync with research/meta_ads_fetcher.py
HISTORY = os.path.join(ROOT, "data", "meta_ads_history.json")

# Meta reports purchases under several action_types depending on attribution
# setup; take the first one present (omni_purchase aggregates web+app).
PURCHASE_KEYS = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")


# ── week helpers ─────────────────────────────────────────────────────────────

def last_completed_week(today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """(monday, sunday) of the most recent fully completed ISO week."""
    today = today or dt.date.today()
    this_monday = today - dt.timedelta(days=today.weekday())
    return this_monday - dt.timedelta(days=7), this_monday - dt.timedelta(days=1)


# ── Meta Insights ────────────────────────────────────────────────────────────

def _action_value(rows: list[dict] | None, keys=PURCHASE_KEYS) -> float:
    for key in keys:
        for row in rows or []:
            if row.get("action_type") == key:
                try:
                    return float(row.get("value") or 0)
                except (TypeError, ValueError):
                    return 0.0
    return 0.0


def fetch_week(since: dt.date, until: dt.date) -> dict:
    """Campaign-level insights for [since, until]; aggregated account totals."""
    r = requests.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{META_AD_ACCOUNT_ID}/insights",
        params={
            "level": "campaign",
            "fields": ("campaign_name,spend,impressions,clicks,inline_link_clicks,"
                       "actions,action_values"),
            "time_range": json.dumps({"since": since.isoformat(),
                                      "until": until.isoformat()}),
            "limit": 100,
            "access_token": META_ACCESS_TOKEN,
        },
        timeout=30,
    )
    if r.status_code != 200:
        try:
            err = r.json().get("error", {})
            raise RuntimeError(f"Meta Insights {r.status_code}: "
                               f"{err.get('message', r.text[:200])}")
        except ValueError:
            raise RuntimeError(f"Meta Insights {r.status_code}: {r.text[:200]}")

    campaigns = []
    for row in r.json().get("data", []) or []:
        spend     = float(row.get("spend") or 0)
        clicks    = int(row.get("inline_link_clicks") or row.get("clicks") or 0)
        imps      = int(row.get("impressions") or 0)
        purchases = _action_value(row.get("actions"))
        revenue   = _action_value(row.get("action_values"))
        campaigns.append({
            "name":       row.get("campaign_name", "?"),
            "spend":      round(spend, 2),
            "impressions": imps,
            "clicks":     clicks,
            "ctr":        round(clicks / imps * 100, 2) if imps else 0.0,
            "cpc":        round(spend / clicks, 2) if clicks else 0.0,
            "purchases":  int(purchases),
            "revenue":    round(revenue, 2),
            "roas":       round(revenue / spend, 2) if spend else 0.0,
        })
    campaigns.sort(key=lambda c: c["spend"], reverse=True)

    spend   = round(sum(c["spend"] for c in campaigns), 2)
    clicks  = sum(c["clicks"] for c in campaigns)
    imps    = sum(c["impressions"] for c in campaigns)
    purch   = sum(c["purchases"] for c in campaigns)
    revenue = round(sum(c["revenue"] for c in campaigns), 2)
    return {
        "week_start": since.isoformat(),
        "week_end":   until.isoformat(),
        "fetched":    dt.date.today().isoformat(),
        "account": {
            "spend":       spend,
            "impressions": imps,
            "clicks":      clicks,
            "ctr":         round(clicks / imps * 100, 2) if imps else 0.0,
            "cpc":         round(spend / clicks, 2) if clicks else 0.0,
            "purchases":   purch,
            "revenue":     revenue,
            "roas":        round(revenue / spend, 2) if spend else 0.0,
            "cpa":         round(spend / purch, 2) if purch else 0.0,
        },
        "campaigns": campaigns,
    }


# ── history + reporting ──────────────────────────────────────────────────────

def load_history() -> list[dict]:
    try:
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(hist: list[dict]) -> None:
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)


def _delta(cur: float, prev: float, pct: bool = True, invert: bool = False) -> str:
    """'+12%' style delta; invert=True flags increases as bad (e.g. CPC)."""
    if prev in (0, 0.0):
        return ""
    ch = (cur - prev) / prev * 100
    arrow = "🔺" if (ch > 0) != invert else "🟢"
    if abs(ch) < 0.5:
        arrow = "▪️"
    return f" ({arrow} {ch:+.0f}%)" if pct else f" ({arrow} {cur - prev:+.2f})"


def build_message(week: dict, prev: dict | None) -> str:
    a, p = week["account"], (prev or {}).get("account", {})
    lines = [
        f"📣 Meta Ads Wochenreport · {week['week_start']} – {week['week_end']}",
        "",
        f"💶 Spend: {a['spend']:.2f} €{_delta(a['spend'], p.get('spend', 0))}",
        f"👀 Impressionen: {a['impressions']:,}{_delta(a['impressions'], p.get('impressions', 0))}",
        f"🖱 Klicks: {a['clicks']:,}{_delta(a['clicks'], p.get('clicks', 0))} · CTR {a['ctr']:.2f}%",
        f"💸 CPC: {a['cpc']:.2f} €{_delta(a['cpc'], p.get('cpc', 0), invert=True)}",
        f"🛒 Käufe: {a['purchases']}{_delta(a['purchases'], p.get('purchases', 0))}"
        + (f" · CPA {a['cpa']:.2f} €" if a["purchases"] else ""),
        f"📈 Umsatz: {a['revenue']:.2f} € · ROAS {a['roas']:.2f}"
        f"{_delta(a['roas'], p.get('roas', 0))}",
    ]
    if week["campaigns"]:
        lines.append("")
        lines.append("Kampagnen (nach Spend):")
        for c in week["campaigns"][:5]:
            lines.append(f"• {c['name'][:40]}: {c['spend']:.0f} € · "
                         f"{c['clicks']} Klicks · {c['purchases']}🛒 · ROAS {c['roas']:.2f}")
    if not week["campaigns"] or a["spend"] == 0:
        lines.append("")
        lines.append("ℹ️ Kein Spend in dieser Woche — liefen Ads?")
    return "\n".join(lines)


def send_report(subject: str, text: str) -> None:
    """All bot communication is email-only (mailer no-ops without creds)."""
    try:
        sys.path.insert(0, ROOT)
        import mailer
        mailer.send_email(subject, text)
    except Exception as e:
        print(f"   ⚠️  report email failed: {e}")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    force = "--force" in sys.argv
    if "--week" in sys.argv:
        since = dt.date.fromisoformat(sys.argv[sys.argv.index("--week") + 1])
        until = since + dt.timedelta(days=6)
    else:
        since, until = last_completed_week()

    if not (META_ACCESS_TOKEN and META_AD_ACCOUNT_ID):
        print("   Meta Ads report: META_ACCESS_TOKEN / META_AD_ACCOUNT_ID missing — skipping")
        return

    hist = load_history()
    if any(w.get("week_start") == since.isoformat() for w in hist) and not force:
        print(f"   Meta Ads report: week {since} already recorded — nothing to do")
        return

    print(f"📣 Meta Ads weekly report — {since} … {until}")
    week = fetch_week(since, until)

    prev = next((w for w in hist
                 if w.get("week_start") == (since - dt.timedelta(days=7)).isoformat()), None)
    if prev is None:
        # first run: fetch the week before too, so the report has WoW deltas
        try:
            prev = fetch_week(since - dt.timedelta(days=7), since - dt.timedelta(days=1))
            hist.append(prev)
        except Exception as e:
            print(f"   ⚠️  previous week fetch failed ({e}) — no deltas")

    hist = [w for w in hist if w.get("week_start") != week["week_start"]] + [week]
    hist.sort(key=lambda w: w.get("week_start", ""))
    save_history(hist[-52:])  # keep one year
    print(f"   💾 history updated ({len(hist[-52:])} weeks): {HISTORY}")

    a = week["account"]
    print(f"   Spend {a['spend']:.2f}€ | {a['clicks']} clicks | "
          f"{a['purchases']} purchases | ROAS {a['roas']:.2f}")
    send_report(f"📣 Meta Ads Wochenreport {week['week_start']} – {week['week_end']}",
                build_message(week, prev))


if __name__ == "__main__":
    main()
