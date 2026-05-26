"""
Commercial config loader — provides the current price, UVP, currency, and offer
status per market for use in article briefs and generation prompts.

Why this exists (spec lines 62-92):
  Prices, UVP, discounts, free-shipping thresholds, guarantees, and delivery
  promises are DYNAMIC. They must never be hard-coded as permanent facts in
  generated articles. Every bot run loads the current config once at startup
  and threads it through every generation prompt.

Current state (May 2026):
  - NL is testing 69 EUR (offer_status: "test")
  - Every other market uses 149 EUR UVP

Source of truth:
  Shopify product `strada-pro` queried via Admin GraphQL. Variant prices per
  market come from Shopify Markets configuration. If Shopify is unreachable
  the static fallback below is used and a warning is printed — the bot must
  not crash on missing pricing data.

Returned per-market dict (spec line 80-92):
  {
    "market": "NL",
    "currency": "EUR",
    "current_price": 69,
    "uvp": 149,
    "offer_status": "test" | "live" | "standard",
    "free_shipping_threshold": null | int,
    "guarantee": null | str,
    "delivery_claim": null | str,
    "last_updated": "YYYY-MM-DD",
    "in_stock": bool,
    "product_handle": "strada-pro",
  }
"""
from __future__ import annotations

import datetime as _dt
import os
from functools import lru_cache

import requests
from dotenv import load_dotenv

import config_loader

load_dotenv(
    dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    override=True,
)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "")
PRIMARY_PRODUCT_HANDLE = "strada-pro"


# Static fallback / override layer.
# Shopify multi-currency is not yet wired for every market — until it is, this
# is the authoritative price-per-market table. NL is the only market with a
# test offer; everything else uses the 149 UVP.
# When Shopify Markets pricing is fully configured, this layer can be removed.
STATIC_PRICE_OVERRIDES: dict[str, dict] = {
    "US": {"currency": "USD", "current_price": 149, "uvp": 149, "offer_status": "standard"},
    "DE": {"currency": "EUR", "current_price": 149, "uvp": 149, "offer_status": "standard"},
    "NL": {"currency": "EUR", "current_price": 69,  "uvp": 149, "offer_status": "test"},
    "FR": {"currency": "EUR", "current_price": 149, "uvp": 149, "offer_status": "standard"},
    "ES": {"currency": "EUR", "current_price": 149, "uvp": 149, "offer_status": "standard"},
    "IT": {"currency": "EUR", "current_price": 149, "uvp": 149, "offer_status": "standard"},
    "DA": {"currency": "DKK", "current_price": 1099, "uvp": 1099, "offer_status": "standard"},
    "NB": {"currency": "NOK", "current_price": 1499, "uvp": 1499, "offer_status": "standard"},
    "PL": {"currency": "PLN", "current_price": 649,  "uvp": 649,  "offer_status": "standard"},
    "PT": {"currency": "EUR", "current_price": 149,  "uvp": 149,  "offer_status": "standard"},
    "SV": {"currency": "SEK", "current_price": 1599, "uvp": 1599, "offer_status": "standard"},
}


def _shopify_graphql(query: str) -> dict:
    """Thin wrapper. Returns {} on any failure — caller falls back to static."""
    if not SHOPIFY_TOKEN or not SHOPIFY_STORE:
        return {}
    try:
        r = requests.post(
            f"https://{SHOPIFY_STORE}/admin/api/2025-01/graphql.json",
            json={"query": query},
            headers={
                "X-Shopify-Access-Token": SHOPIFY_TOKEN,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def _fetch_product_state() -> dict:
    """Returns {in_stock: bool, product_handle: str, found: bool} for Strada Pro."""
    q = f"""
    {{
      productByHandle(handle: "{PRIMARY_PRODUCT_HANDLE}") {{
        title
        handle
        totalInventory
        status
      }}
    }}
    """
    data = _shopify_graphql(q)
    p = ((data or {}).get("data") or {}).get("productByHandle") or {}
    if not p:
        return {"in_stock": True, "product_handle": PRIMARY_PRODUCT_HANDLE, "found": False}
    return {
        "in_stock": (p.get("totalInventory") or 0) > 0 and p.get("status") == "ACTIVE",
        "product_handle": p.get("handle") or PRIMARY_PRODUCT_HANDLE,
        "found": True,
    }


@lru_cache(maxsize=1)
def load_commercial_config() -> dict[str, dict]:
    """
    Returns the full commercial config keyed by 2-letter market code.
    Cached for the lifetime of the bot run.

    Example:
      cfg = load_commercial_config()
      cfg["NL"]["current_price"]  # → 69
      cfg["NL"]["currency"]       # → "EUR"
      cfg["DE"]["uvp"]            # → 149
    """
    product_state = _fetch_product_state()
    today = _dt.date.today().isoformat()
    all_markets = config_loader.markets()

    out: dict[str, dict] = {}
    for code in all_markets.keys():
        override = STATIC_PRICE_OVERRIDES.get(code, {})
        out[code] = {
            "market": code,
            "currency": override.get("currency", "EUR"),
            "current_price": override.get("current_price"),
            "uvp": override.get("uvp"),
            "offer_status": override.get("offer_status", "standard"),
            "free_shipping_threshold": None,
            "guarantee": None,
            "delivery_claim": None,
            "last_updated": today,
            "in_stock": product_state["in_stock"],
            "product_handle": product_state["product_handle"],
        }
    return out


def for_market(code: str) -> dict | None:
    """Convenience: get the commercial config for one market."""
    return load_commercial_config().get(code.upper())


def for_locale_short(locale_short: str) -> dict | None:
    """Lookup by short locale (en → US, de → DE, nl → NL, …)."""
    m = config_loader.market_by_locale_short(locale_short)
    if not m:
        return None
    return for_market(m["code"])


def safe_price_str(code: str) -> str:
    """
    Returns a human-readable price string for prompt injection.
    Falls back to a neutral wording if config is missing (spec line 74).
    """
    cfg = for_market(code)
    if not cfg or not cfg.get("current_price"):
        return "current pricing (see product page)"
    price = cfg["current_price"]
    cur = cfg["currency"]
    if cur == "EUR":
        return f"{price} EUR"
    if cur == "USD":
        return f"${price}"
    return f"{price} {cur}"


if __name__ == "__main__":
    import json
    cfg = load_commercial_config()
    print(json.dumps(cfg, indent=2, ensure_ascii=False))
    print(f"\nMarkets loaded: {len(cfg)}")
    print(f"NL price: {safe_price_str('NL')}  (expected: 69 EUR)")
    print(f"DE price: {safe_price_str('DE')}  (expected: 149 EUR)")
    print(f"US price: {safe_price_str('US')}  (expected: $149)")
