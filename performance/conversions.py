"""
Conversion performance (Phase 6).

Pulls Shopify orders for the current 28-day window and the previous one, and
attributes each order to the landing page it came in on (Shopify's `landing_site`
= first page of the session that led to the order). This is the free, immediate
proxy for "which page actually drives sales" — good enough to make the loop
optimise for REVENUE, not just clicks.

Output: data/processed/conversion_performance.json
  {
    date, windows,
    by_page: { url: {orders, revenue, prev_orders, prev_revenue} },
    totals:  {orders, revenue, prev_orders, prev_revenue, currency}
  }

Credentials reused from the bot's .env (SHOPIFY_TOKEN, SHOPIFY_STORE) — no new
setup. Best-effort: if the token is missing or the API errors, returns an empty
structure and the loop simply falls back to click-based ranking.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import urllib.parse
from collections import defaultdict

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(ROOT, ".env"), override=True)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "")
OUTPUT_PATH   = os.path.join(ROOT, "data", "processed", "conversion_performance.json")

SITE = "https://velluto-shop.com"
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}


def _normalize_landing(landing: str) -> str | None:
    """Turn a Shopify landing_site value into a canonical https://velluto-shop.com/<path> URL.

    landing_site can be a full URL or a bare path, may carry query/utm/locale.
    We strip query + fragment and any /<locale>/ prefix so it matches GSC page URLs.
    """
    if not landing:
        return None
    path = landing
    if path.startswith("http"):
        path = urllib.parse.urlparse(path).path
    else:
        path = urllib.parse.urlparse("https://x" + (path if path.startswith("/") else "/" + path)).path
    if not path:
        path = "/"
    # strip leading locale prefix like /nl/, /de-at/
    parts = path.split("/")
    if len(parts) > 1 and 2 <= len(parts[1]) <= 5 and parts[1].replace("-", "").isalpha() \
            and parts[1].lower() == parts[1] and parts[1] not in ("blogs", "products", "pages"):
        path = "/" + "/".join(parts[2:])
    path = path.rstrip("/") or "/"
    return SITE + path


def _fetch_orders(start: str, end: str) -> list[dict]:
    """Fetch orders created in [start, end] (ISO dates). Paginated REST."""
    if not (SHOPIFY_TOKEN and SHOPIFY_STORE):
        return []
    orders: list[dict] = []
    url = (f"https://{SHOPIFY_STORE}/admin/api/2024-01/orders.json"
           f"?status=any&created_at_min={start}T00:00:00Z&created_at_max={end}T23:59:59Z"
           "&fields=id,created_at,landing_site,referring_site,total_price,currency,financial_status"
           "&limit=250")
    try:
        while url:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            orders.extend(r.json().get("orders", []))
            link = r.headers.get("Link", "")
            nxt = None
            for part in link.split(","):
                if 'rel="next"' in part:
                    nxt = part.split(";")[0].strip(" <>")
            url = nxt
    except Exception as e:
        print(f"      ⚠️  Shopify orders fetch error: {e}")
    return orders


def _aggregate(orders: list[dict]) -> tuple[dict, float, int, str]:
    by_page: dict[str, dict] = defaultdict(lambda: {"orders": 0, "revenue": 0.0})
    total_rev = 0.0
    currency = "EUR"
    for o in orders:
        # Count only orders that represent real money (paid / partially paid).
        if (o.get("financial_status") or "") in ("voided", "refunded"):
            continue
        try:
            rev = float(o.get("total_price") or 0)
        except (TypeError, ValueError):
            rev = 0.0
        currency = o.get("currency") or currency
        url = _normalize_landing(o.get("landing_site") or "")
        total_rev += rev
        if url:
            by_page[url]["orders"] += 1
            by_page[url]["revenue"] = round(by_page[url]["revenue"] + rev, 2)
    return by_page, round(total_rev, 2), len(orders), currency


def classify(today: _dt.date | None = None) -> dict:
    today = today or _dt.date.today()
    curr_end   = today.isoformat()
    curr_start = (today - _dt.timedelta(days=28)).isoformat()
    prev_end   = (today - _dt.timedelta(days=29)).isoformat()
    prev_start = (today - _dt.timedelta(days=56)).isoformat()

    curr_orders = _fetch_orders(curr_start, curr_end)
    prev_orders = _fetch_orders(prev_start, prev_end)

    curr_by, curr_rev, curr_n, currency = _aggregate(curr_orders)
    prev_by, prev_rev, prev_n, _        = _aggregate(prev_orders)

    by_page: dict[str, dict] = {}
    for url in set(curr_by) | set(prev_by):
        c = curr_by.get(url, {"orders": 0, "revenue": 0.0})
        p = prev_by.get(url, {"orders": 0, "revenue": 0.0})
        by_page[url] = {
            "orders":       c["orders"],
            "revenue":      c["revenue"],
            "prev_orders":  p["orders"],
            "prev_revenue": p["revenue"],
        }

    return {
        "date": today.isoformat(),
        "windows": {"current": [curr_start, curr_end], "previous": [prev_start, prev_end]},
        "by_page": by_page,
        "totals": {
            "orders": curr_n, "revenue": curr_rev,
            "prev_orders": prev_n, "prev_revenue": prev_rev,
            "currency": currency,
        },
        "available": bool(curr_orders or prev_orders),
    }


def _save(payload: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def run() -> dict:
    result = classify()
    _save(result)
    t = result["totals"]
    if not result["available"]:
        print("   ⚠️  Conversions: no Shopify orders read (check SHOPIFY_TOKEN) — loop uses clicks only.")
    else:
        print(f"   ✓ Conversions: {t['orders']} orders / {t['revenue']} {t['currency']} (28d), "
              f"{len(result['by_page'])} landing pages with sales")
    return result


def load() -> dict:
    if not os.path.exists(OUTPUT_PATH):
        return {}
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


if __name__ == "__main__":
    res = run()
    top = sorted(res["by_page"].items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:10]
    print(json.dumps({"totals": res["totals"],
                      "top_pages": [{"url": u, **v} for u, v in top]},
                     indent=2, ensure_ascii=False))
