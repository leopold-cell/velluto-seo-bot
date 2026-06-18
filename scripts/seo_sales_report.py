#!/usr/bin/env python3
"""
Monthly SEO-sales report — TRUE organic attribution.

Counts orders whose acquisition channel was organic search (Shopify
customerJourneySummary.firstVisit.sourceType == "SEO"), excludes 0 EUR
B2B/wholesale/free orders, and reports the previous calendar month vs the one
before, plus progress toward the goal (default 20 SEO sales/month).

Sends a Telegram summary (same bot the daily SEO job uses) and appends to
output/seo_sales_history.json so the trend is tracked month over month.

Usage:
  python3 scripts/seo_sales_report.py                # previous calendar month
  python3 scripts/seo_sales_report.py --month 2026-06
  python3 scripts/seo_sales_report.py --no-telegram  # print only

Cron (1st of each month, 07:00):
  0 7 1 * *  cd /root/velluto/velluto-seo-bot && python3 scripts/seo_sales_report.py >> /var/log/seo-bot.log 2>&1
"""
import argparse
import calendar
import datetime as dt
import json
import os

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"), override=True)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
API = f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json"

GOAL = 20
HISTORY = os.path.join(ROOT, "output", "seo_sales_history.json")


def _month_range(year: int, month: int) -> tuple[str, str]:
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _fetch_orders(start: str, end: str) -> list[dict]:
    orders, cursor = [], None
    q = """
    query($q: String!, $after: String) {
      orders(first: 100, query: $q, after: $after, sortKey: CREATED_AT) {
        pageInfo { hasNextPage endCursor }
        nodes {
          totalPriceSet { shopMoney { amount } }
          customerJourneySummary {
            firstVisit { source sourceType landingPage }
          }
        }
      }
    }"""
    qstr = f"created_at:>={start} created_at:<={end}"
    while True:
        r = requests.post(API, headers=HEADERS,
                          json={"query": q, "variables": {"q": qstr, "after": cursor}}, timeout=30)
        data = (r.json().get("data") or {}).get("orders") or {}
        orders.extend(data.get("nodes", []))
        if not data.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = data["pageInfo"]["endCursor"]
    return orders


def _is_seo(o: dict) -> bool:
    fv = ((o.get("customerJourneySummary") or {}).get("firstVisit")) or {}
    return (fv.get("sourceType") or "").upper() == "SEO"


def analyze(start: str, end: str) -> dict:
    orders = _fetch_orders(start, end)
    seo_orders, seo_rev = 0, 0.0
    by_page: dict[str, dict] = {}
    for o in orders:
        try:
            rev = float(o["totalPriceSet"]["shopMoney"]["amount"])
        except (KeyError, TypeError, ValueError):
            rev = 0.0
        if rev <= 0:            # skip B2B / free / 0 EUR
            continue
        if not _is_seo(o):
            continue
        seo_orders += 1
        seo_rev += rev
        lp = (((o.get("customerJourneySummary") or {}).get("firstVisit")) or {}).get("landingPage") or "(unknown)"
        b = by_page.setdefault(lp, {"orders": 0, "revenue": 0.0})
        b["orders"] += 1
        b["revenue"] = round(b["revenue"] + rev, 2)
    top = sorted(by_page.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:5]
    return {"orders": seo_orders, "revenue": round(seo_rev, 2), "top_pages": top}


def _send_telegram(text: str) -> None:
    if not (TG_TOKEN and TG_CHAT):
        print("   (Telegram not configured — skipping send)")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=15)
    except Exception as e:
        print(f"   ⚠️  Telegram send failed: {e}")


def _save_history(entry: dict) -> None:
    hist = []
    if os.path.exists(HISTORY):
        try:
            hist = json.load(open(HISTORY))
        except Exception:
            hist = []
    hist = [h for h in hist if h.get("month") != entry["month"]]
    hist.append(entry)
    hist.sort(key=lambda h: h["month"])
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    json.dump(hist, open(HISTORY, "w"), indent=2, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (default: previous calendar month)")
    ap.add_argument("--no-telegram", action="store_true")
    args = ap.parse_args()

    today = dt.date.today()
    if args.month:
        y, m = map(int, args.month.split("-"))
    else:
        y, m = _prev_month(today.year, today.month)
    py, pm = _prev_month(y, m)

    cur = analyze(*_month_range(y, m))
    prv = analyze(*_month_range(py, pm))

    label = f"{calendar.month_name[m]} {y}"
    delta = cur["orders"] - prv["orders"]
    pct   = (cur["orders"] / GOAL * 100) if GOAL else 0
    bar_n = min(10, round(cur["orders"] / GOAL * 10)) if GOAL else 0
    bar   = "█" * bar_n + "░" * (10 - bar_n)
    status = "🎯 GOAL HIT" if cur["orders"] >= GOAL else f"{pct:.0f}% of goal"

    lines = [
        f"<b>📈 Velluto SEO Sales — {label}</b>",
        "",
        f"Organic-search sales: <b>{cur['orders']}</b>  ({delta:+d} vs {calendar.month_name[pm]})",
        f"SEO revenue: <b>{cur['revenue']} EUR</b>  (prev {prv['revenue']})",
        f"Goal: {cur['orders']}/{GOAL}  {bar}  {status}",
    ]
    if cur["top_pages"]:
        lines.append("")
        lines.append("Top SEO landing pages:")
        for url, v in cur["top_pages"]:
            short = url.replace("https://velluto-shop.com", "")
            lines.append(f"• {short[:48]} — {v['orders']} / {v['revenue']} EUR")
    msg = "\n".join(lines)

    print(msg.replace("<b>", "").replace("</b>", ""))
    _save_history({
        "month": f"{y:04d}-{m:02d}", "seo_orders": cur["orders"],
        "seo_revenue": cur["revenue"], "goal": GOAL,
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
    })
    if not args.no_telegram:
        _send_telegram(msg)


if __name__ == "__main__":
    main()
