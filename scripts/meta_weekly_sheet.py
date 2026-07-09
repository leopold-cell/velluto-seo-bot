#!/usr/bin/env python3
"""
Weekly Meta × Shopify numbers for the tracking sheet — from 2024-08-01 on.

Produces exactly the sheet's column layout, one row per ISO week (Mon-Sun,
newest first, dates as MM/DD/YY):

  Date | Spent | Net Sales | nCustomers | Purchases | ATC | Out. Clicks
       | Impressions | Reach | Total Reach

Sources (all READ-ONLY):
- Meta Insights (account level, time_increment=7): spend, impressions, reach,
  purchases, add-to-cart, outbound clicks per week.
- Meta "Total Reach": cumulative de-duplicated reach since START — one extra
  API call per week (matches the running numbers already in the sheet).
  Skip with --skip-total-reach if you're in a hurry.
- Shopify orders: Net Sales = order totals minus refunds (test orders
  excluded); nCustomers = distinct customers with an order that week.

Output: output/meta_weekly_sheet.csv — import into Google Sheets via
File → Import, or pass --upload to create a real Google Sheet in Drive
(reuses the existing drive_upload OAuth; prints the docs.google.com URL).

Usage (on the VPS, where the credentials live):
  export SHOPIFY_TOKEN="$(python3 mint_shopify_token.py)"
  python3 scripts/meta_weekly_sheet.py                # writes the CSV
  python3 scripts/meta_weekly_sheet.py --upload       # + Google Sheet in Drive
  python3 scripts/meta_weekly_sheet.py --since 2024-08-01 --skip-total-reach
"""
import csv
import datetime as dt
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"), override=True)

META_ACCESS_TOKEN  = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")
SHOPIFY_TOKEN      = os.getenv("SHOPIFY_TOKEN", "")
SHOPIFY_STORE      = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
GRAPH_VERSION      = "v22.0"

DEFAULT_SINCE = "2024-08-01"
OUT_CSV       = os.path.join(ROOT, "output", "meta_weekly_sheet.csv")

HEADERS_ROW = ["Date", "Spent", "Net Sales", "nCustomers", "Purchases",
               "ATC", "Out. Clicks", "Impressions", "Reach", "Total Reach"]

PURCHASE_KEYS = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")
ATC_KEYS      = ("omni_add_to_cart", "add_to_cart",
                 "offsite_conversion.fb_pixel_add_to_cart")


# ── weeks ────────────────────────────────────────────────────────────────────

def build_weeks(since: dt.date, today: dt.date | None = None) -> list[tuple[dt.date, dt.date]]:
    """[(monday, sunday), …] for every completed week from the week containing
    `since` up to the last completed week, ascending."""
    today = today or dt.date.today()
    start = since - dt.timedelta(days=since.weekday())          # monday of first week
    last_monday = today - dt.timedelta(days=today.weekday())    # current week excluded
    weeks, m = [], start
    while m < last_monday:
        weeks.append((m, m + dt.timedelta(days=6)))
        m += dt.timedelta(days=7)
    return weeks


def label(monday: dt.date) -> str:
    return monday.strftime("%m/%d/%y")


# ── Meta ─────────────────────────────────────────────────────────────────────

def _actions_value(rows, keys) -> int:
    for key in keys:
        for row in rows or []:
            if row.get("action_type") == key:
                try:
                    return int(float(row.get("value") or 0))
                except (TypeError, ValueError):
                    return 0
    return 0


def fetch_meta_weekly(since: dt.date, until: dt.date) -> dict[str, dict]:
    """{monday_iso: {...}} via ONE insights request with weekly buckets."""
    out: dict[str, dict] = {}
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{META_AD_ACCOUNT_ID}/insights"
    params = {
        "level": "account",
        "fields": "spend,impressions,reach,actions,outbound_clicks",
        "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        "time_increment": 7,
        "limit": 200,
        "access_token": META_ACCESS_TOKEN,
    }
    while url:
        r = requests.get(url, params=params, timeout=60)
        if r.status_code != 200:
            err = (r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {})
            raise RuntimeError(f"Meta Insights {r.status_code}: {err.get('message', r.text[:200])}")
        data = r.json()
        for row in data.get("data", []):
            out[row.get("date_start", "")] = {
                "spend":       round(float(row.get("spend") or 0), 2),
                "impressions": int(row.get("impressions") or 0),
                "reach":       int(row.get("reach") or 0),
                "purchases":   _actions_value(row.get("actions"), PURCHASE_KEYS),
                "atc":         _actions_value(row.get("actions"), ATC_KEYS),
                "out_clicks":  _actions_value(row.get("outbound_clicks"), ("outbound_click",)),
            }
        url = (data.get("paging") or {}).get("next")
        params = None  # next-URL already carries everything
    return out


def fetch_total_reach(since: dt.date, until: dt.date) -> int:
    """De-duplicated reach for [since, until] — the sheet's running 'Total Reach'."""
    r = requests.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{META_AD_ACCOUNT_ID}/insights",
        params={"level": "account", "fields": "reach",
                "time_range": json.dumps({"since": since.isoformat(),
                                          "until": until.isoformat()}),
                "access_token": META_ACCESS_TOKEN},
        timeout=60)
    if r.status_code != 200:
        return 0
    data = r.json().get("data", [])
    return int(data[0].get("reach") or 0) if data else 0


# ── Shopify ──────────────────────────────────────────────────────────────────

def fetch_shopify_orders(since: dt.date) -> list[dict]:
    """All orders since `since` (any status, test orders excluded)."""
    out, url = [], (
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/orders.json"
        f"?status=any&limit=250&created_at_min={since.isoformat()}T00:00:00Z"
        "&fields=id,created_at,total_price,customer,refunds,test,financial_status"
    )
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        out.extend(o for o in r.json().get("orders", []) if not o.get("test"))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
        time.sleep(0.6)
    return out


def aggregate_shopify(orders: list[dict],
                      weeks: list[tuple[dt.date, dt.date]]) -> dict[str, dict]:
    """{monday_iso: {net_sales, customers}} — net = totals minus refunds."""
    agg = {m.isoformat(): {"net_sales": 0.0, "customers": set()} for m, _ in weeks}
    for o in orders:
        try:
            created = dt.datetime.fromisoformat(o["created_at"]).date()
        except Exception:
            continue
        monday = (created - dt.timedelta(days=created.weekday())).isoformat()
        if monday not in agg:
            continue
        net = float(o.get("total_price") or 0)
        for ref in o.get("refunds") or []:
            for tx in ref.get("transactions") or []:
                try:
                    net -= float(tx.get("amount") or 0)
                except (TypeError, ValueError):
                    pass
        agg[monday]["net_sales"] += net
        cust = (o.get("customer") or {}).get("id")
        if cust:
            agg[monday]["customers"].add(cust)
    return {k: {"net_sales": round(v["net_sales"], 2),
                "customers": len(v["customers"])} for k, v in agg.items()}


# ── output ───────────────────────────────────────────────────────────────────

def build_rows(weeks, meta_by_week, shopify_by_week, total_reach_by_week) -> list[list]:
    rows = [HEADERS_ROW]
    for monday, _sunday in reversed(weeks):        # newest first, like the sheet
        k = monday.isoformat()
        m = meta_by_week.get(k, {})
        s = shopify_by_week.get(k, {})
        rows.append([
            label(monday),
            m.get("spend", 0),
            s.get("net_sales", 0),
            s.get("customers", 0),
            m.get("purchases", 0),
            m.get("atc", 0),
            m.get("out_clicks", 0),
            m.get("impressions", 0),
            m.get("reach", 0),
            total_reach_by_week.get(k, ""),
        ])
    return rows


def upload_as_google_sheet(csv_path: str) -> str:
    """CSV → real Google Sheet in Drive (reuses drive_upload OAuth)."""
    from drive_upload import _service, is_configured
    if not is_configured():
        print("   ▶ Drive not configured (GOOGLE_DRIVE_* / service account) — skipping upload")
        return ""
    from googleapiclient.http import MediaFileUpload
    svc = _service()
    if svc is None:
        return ""
    meta = {"name": f"Velluto Weekly Meta × Shopify ({dt.date.today().isoformat()})",
            "mimeType": "application/vnd.google-apps.spreadsheet"}
    folder = os.getenv("GDRIVE_FOLDER_ID", "").strip()
    if folder:
        meta["parents"] = [folder]
    media = MediaFileUpload(csv_path, mimetype="text/csv")
    f = svc.files().create(body=meta, media_body=media, fields="id",
                           supportsAllDrives=True).execute()
    return f"https://docs.google.com/spreadsheets/d/{f['id']}"


def main() -> None:
    since = dt.date.fromisoformat(
        sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else DEFAULT_SINCE)
    weeks = build_weeks(since)
    print(f"📊 Weekly sheet export — {len(weeks)} weeks "
          f"({weeks[0][0]} … {weeks[-1][1]})")

    meta_by_week: dict[str, dict] = {}
    total_reach: dict[str, int] = {}
    if META_ACCESS_TOKEN and META_AD_ACCOUNT_ID:
        print("   Meta: fetching weekly insights (1 batched call)…")
        meta_by_week = fetch_meta_weekly(weeks[0][0], weeks[-1][1])
        if "--skip-total-reach" not in sys.argv:
            print(f"   Meta: cumulative Total Reach ({len(weeks)} calls)…")
            for monday, sunday in weeks:
                total_reach[monday.isoformat()] = fetch_total_reach(weeks[0][0], sunday)
                time.sleep(0.3)
    else:
        print("   ⚠️  META_ACCESS_TOKEN / META_AD_ACCOUNT_ID missing — Meta columns stay 0")

    shopify_by_week: dict[str, dict] = {}
    if SHOPIFY_TOKEN:
        print("   Shopify: sweeping orders…")
        orders = fetch_shopify_orders(weeks[0][0])
        print(f"   Shopify: {len(orders)} orders")
        shopify_by_week = aggregate_shopify(orders, weeks)
    else:
        print("   ⚠️  SHOPIFY_TOKEN missing — Shopify columns stay 0 "
              "(run: export SHOPIFY_TOKEN=\"$(python3 mint_shopify_token.py)\")")

    rows = build_rows(weeks, meta_by_week, shopify_by_week, total_reach)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    print(f"   💾 {OUT_CSV} ({len(rows)-1} weeks)")

    if "--upload" in sys.argv:
        url = upload_as_google_sheet(OUT_CSV)
        if url:
            print(f"   ✅ Google Sheet: {url}")
    else:
        print("   → Import in dein Sheet: Datei → Importieren → CSV hochladen "
              "(oder mit --upload direkt als Google Sheet in Drive)")


if __name__ == "__main__":
    main()
