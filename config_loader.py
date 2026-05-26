"""
Shared loader for the YAML config files in /config.
Cached for the lifetime of a single bot run.
Used by: research/, decision/, briefs/, performance/, commercial_config.py, seo_bot.py
"""
import os
from functools import lru_cache
from typing import Any

import yaml


CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{name}.yml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def markets() -> dict[str, dict]:
    """Return the {US: {...}, DE: {...}, ...} map from config/markets.yml."""
    return _load("markets")["markets"]


def market(code: str) -> dict | None:
    """Lookup one market by 2-letter code (US/DE/NL/...). None if not found."""
    return markets().get(code.upper())


def market_by_locale_short(locale_short: str) -> dict | None:
    """Lookup by short locale (en, de, nl, fr, …, pt-PT). Returns the market dict + code."""
    for code, m in markets().items():
        if m["locale_short"] == locale_short:
            return {**m, "code": code}
    return None


def locale_geo() -> dict[str, tuple[int, str]]:
    """
    Drop-in replacement for the LOCALE_GEO constant in keyword_research.py.
    Returns {locale_short: (location_code, language_code)}.
    """
    out = {}
    for m in markets().values():
        out[m["locale_short"]] = (m["dataforseo_location_code"], m["language_code"])
    return out


def competitors() -> dict:
    return _load("competitors")


def forbidden_outbound_domains() -> set[str]:
    """All competitor domains that must never appear as outbound links in Velluto content."""
    c = competitors()
    domains = set()
    for entry in c.get("core_competitors", []):
        domains.add(entry["domain"].lower())
    for d in c.get("watchlist", []):
        domains.add(d.lower())
    return domains


def buyer_intent_rules() -> dict:
    return _load("buyer_intent_rules")


def velluto_positioning() -> dict:
    return _load("velluto_positioning")


def scoring_weights() -> dict:
    return _load("scoring_weights")


def publishing_rules() -> dict:
    return _load("publishing_rules")


def get(name: str) -> Any:
    """Generic loader. e.g. config_loader.get('publishing_rules')."""
    return _load(name)


if __name__ == "__main__":
    import json
    print("=== markets ===")
    print(json.dumps(markets(), indent=2))
    print("\n=== locale_geo ===")
    print(locale_geo())
    print("\n=== forbidden_outbound_domains ===")
    print(forbidden_outbound_domains())
    print("\n=== scoring weights ===")
    print(json.dumps(scoring_weights()["weights"], indent=2))
