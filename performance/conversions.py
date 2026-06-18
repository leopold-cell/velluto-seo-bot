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

# ── Channel attribution (Phase 6.1) ─────────────────────────────────────────
# Orders from PAID traffic (Meta/Google ads etc.) must NOT count as SEO revenue —
# otherwise the loop "optimises" the homepage that ads land on. We detect paid via
# click-IDs and UTM markers on landing_site, plus social referrers, and exclude them.
PAID_CLICK_IDS   = ("fbclid", "gclid", "ttclid", "msclkid", "twclid", "li_fat_id", "igshid")
PAID_UTM_SOURCES = {"facebook", "instagram", "ig", "fb", "meta", "tiktok", "snapchat",
                    "pinterest", "youtube", "adwords", "googleads", "google_ads"}
PAID_UTM_MEDIUMS = {"cpc", "ppc", "paid", "paid_social", "paidsocial", "paid-social",
                    "display", "social_paid", "retargeting", "remarketing", "ads"}
PAID_REFERRERS   = ("facebook.", "instagram.", "fb.", "l.facebook", "lm.facebook",
                    "fb.me", "ig.me", "tiktok.", "snapchat.")
# Landing paths that are never SEO content/money pages (coupon links, funnel pages).
EXCLUDED_PATH_PREFIXES = ("/discount/", "/cart", "/checkout", "/account", "/tools",
                          "/apps", "/cdn", "/a/", "/wpm@")


def _is_paid_order(landing: str, referring: str) -> bool:
    s = (landing or "").lower()
    if any(cid in s for cid in PAID_CLICK_IDS):
        return True
    try:
        q = urllib.parse.urlparse(s if s.startswith("http") else "https://x/" + s.lstrip("/")).query
        params = urllib.parse.parse_qs(q)
        if (params.get("utm_source", [""])[0] or "").lower() in PAID_UTM_SOURCES:
            return True
        if (params.get("utm_medium", [""])[0] or "").lower() in PAID_UTM_MEDIUMS:
            return True
    except Exception:
        pass
    ref = (referring or "").lower()
    return any(r in ref for r in PAID_REFERRERS)


def _excluded_page(url: str) -> bool:
    if not url:
        return True
    path = url.replace(SITE, "") or "/"
    return any(path.startswith(p) for p in EXCLUDED_PATH_PREFIXES)


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


def _aggregate(orders: list[dict]) -> dict:
    """Split orders into SEO (organic/direct/referral) vs PAID, attribute SEO ones by page."""
    by_page: dict[str, dict] = defaultdict(lambda: {"orders": 0, "revenue": 0.0})
    seo_rev = paid_rev = 0.0
    seo_n = paid_n = 0
    currency = "EUR"
    for o in orders:
        # Count only orders that represent real money (skip voided / refunded).
        if (o.get("financial_status") or "") in ("voided", "refunded"):
            continue
        try:
            rev = float(o.get("total_price") or 0)
        except (TypeError, ValueError):
            rev = 0.0
        currency = o.get("currency") or currency
        landing   = o.get("landing_site") or ""
        referring = o.get("referring_site") or ""
        if _is_paid_order(landing, referring):
            paid_rev += rev
            paid_n += 1
            continue
        # SEO/organic/direct bucket
        seo_rev += rev
        seo_n += 1
        url = _normalize_landing(landing)
        if url and not _excluded_page(url):
            by_page[url]["orders"] += 1
            by_page[url]["revenue"] = round(by_page[url]["revenue"] + rev, 2)
    return {
        "by_page":      dict(by_page),
        "seo_revenue":  round(seo_rev, 2),
        "seo_orders":   seo_n,
        "paid_revenue": round(paid_rev, 2),
        "paid_orders":  paid_n,
        "currency":     currency,
    }


def classify(today: _dt.date | None = None) -> dict:
    today = today or _dt.date.today()
    curr_end   = today.isoformat()
    curr_start = (today - _dt.timedelta(days=28)).isoformat()
    prev_end   = (today - _dt.timedelta(days=29)).isoformat()
    prev_start = (today - _dt.timedelta(days=56)).isoformat()

    curr_orders = _fetch_orders(curr_start, curr_end)
    prev_orders = _fetch_orders(prev_start, prev_end)

    cur = _aggregate(curr_orders)
    prv = _aggregate(prev_orders)
    curr_by, prev_by = cur["by_page"], prv["by_page"]

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
        "by_page": by_page,   # SEO/organic only — paid (Meta/Google ads) excluded
        "totals": {
            # `revenue`/`orders` = SEO/organic only (what the loop optimises for)
            "orders": cur["seo_orders"], "revenue": cur["seo_revenue"],
            "prev_orders": prv["seo_orders"], "prev_revenue": prv["seo_revenue"],
            # paid shown for context, never fed into scaling decisions
            "paid_orders": cur["paid_orders"], "paid_revenue": cur["paid_revenue"],
            "prev_paid_orders": prv["paid_orders"], "prev_paid_revenue": prv["paid_revenue"],
            "currency": cur["currency"],
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
        print(f"   ✓ Conversions: SEO/organic {t['orders']} orders / {t['revenue']} {t['currency']} "
              f"(paid excluded: {t.get('paid_orders',0)} orders / {t.get('paid_revenue',0)}) — "
              f"{len(result['by_page'])} SEO pages with sales")
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
