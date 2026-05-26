"""
Per-market localization brief generator.

For each non-US market locale, builds a brief that includes:
  - local_primary_keyword (validated against local SERP if available)
  - local_secondary_keywords (extracted from local PAA + related searches)
  - local_search_intent
  - rewrite_level
  - local_adaptation_notes (cycling culture references, terminology)
  - cta_url (locale-specific)
  - market price info (from commercial config)

Phase 4 MVP: mechanical only — no extra Haiku call. The adaptation prompt
in seo_bot.generate_market_adaptation already does Haiku-based rewriting,
this brief just enriches that prompt's inputs.

Output: output/localization_briefs/<locale>.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any

import config_loader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(ROOT, "output", "localization_briefs")


# Cycling culture context per market (used in the adaptation prompt)
CYCLING_CONTEXT = {
    "de":    "Rennrad-Touren in Alpen, Mittelgebirge und auf Norddeutschen Routen; Schwerpunkt auf Schutz und Performance",
    "nl":    "wielrennen in Nederland — wind, regen, vlakke routes, klimkilometers in Limburg",
    "fr":    "cyclisme route en France — Pyrénées, Provence, ascensions du Tour",
    "es":    "ciclismo de carretera en España — Pirineos, Sierra Nevada, rutas costeras",
    "it":    "ciclismo su strada in Italia — Dolomiti, Apennini, dolce vita",
    "da":    "landevejscykling i Danmark — flade ruter, vind",
    "nb":    "landeveissykling i Norge — fjell, kjølig klima, kort sommer",
    "pl":    "kolarstwo szosowe w Polsce — Beskidy, Bieszczady",
    "pt-PT": "ciclismo de estrada em Portugal — Serra da Estrela, costa atlântica",
    "sv":    "landsvägscykling i Sverige — långa avstånd, varierat klimat",
}


def _local_keyword_from_serps(locale_short: str, master_keyword: str,
                               research: dict) -> str:
    """
    If we have a SERP snapshot for this locale matching the master keyword,
    use the master keyword. Otherwise return master_keyword as-is (Haiku will translate).
    Future: validate by examining PAA + related_searches for stronger local variants.
    """
    serps = (research.get("serps") or {}).get("snapshots") or []
    market_code = (config_loader.market_by_locale_short(locale_short) or {}).get("code")
    if not market_code:
        return master_keyword
    for s in serps:
        if s["market"] == market_code and s["keyword"].lower() == master_keyword.lower():
            return master_keyword
    return master_keyword


def _local_paa_secondaries(locale_short: str, research: dict, n: int = 5) -> list[str]:
    """Pull high-intent PAA questions for this locale (any keyword) as secondaries."""
    market_code = (config_loader.market_by_locale_short(locale_short) or {}).get("code")
    if not market_code:
        return []
    paa = (research.get("paa") or {}).get("extracted") or []
    out: list[str] = []
    for snap in paa:
        if snap["market"] == market_code:
            for q in snap.get("questions") or []:
                if q.get("buyer_intent_score", 0) >= 70:
                    out.append(q["question"])
                if len(out) >= n:
                    break
        if len(out) >= n:
            break
    return out


def build_localization_brief(locale_short: str, master_brief: dict,
                              research: dict, commercial: dict | None) -> dict:
    """
    Build the per-market brief. Returns a dict that gets passed alongside
    the master brief into generate_market_adaptation.
    """
    market = config_loader.market_by_locale_short(locale_short) or {}
    market_code = market.get("code")
    cycling_ctx = CYCLING_CONTEXT.get(locale_short, "local road cycling culture")

    local_kw = _local_keyword_from_serps(locale_short, master_brief["primary_keyword"], research)
    secondaries = _local_paa_secondaries(locale_short, research)

    commercial_for_market = (commercial or {}).get(market_code) if market_code else None

    brief = {
        "brief_type":       "localization_brief",
        "date":             _dt.date.today().isoformat(),
        "locale":           market.get("locale", locale_short),
        "locale_short":     locale_short,
        "market_code":      market_code,
        "master_topic":     master_brief["topic"],
        "local_primary_keyword":   local_kw,
        "local_secondary_keywords": secondaries,
        "local_search_intent":     master_brief.get("search_intent", "commercial investigation"),
        "rewrite_level":           "high",
        "local_adaptation_notes": [
            f"Cycling culture context: {cycling_ctx}",
            "Use local cycling terminology naturally (e.g. Rennrad, fietsbril, vélo, ciclismo)",
            "Avoid literal translations of brand-y phrases like 'cycling sunglasses' — use what locals search for",
            f"Mention price as {commercial_for_market['current_price']} {commercial_for_market['currency']}"
            if commercial_for_market and commercial_for_market.get("current_price")
            else "Pricing: use current commercial config (no hard-coded values)",
        ],
        "cta_url":            f"https://velluto-shop.com/{locale_short.split('-')[0]}/products/strada-pro",
        "commercial":         commercial_for_market,
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{locale_short}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(brief, f, indent=2, ensure_ascii=False)
    return brief


def build_all_localization_briefs(master_brief: dict, research: dict,
                                   commercial: dict | None,
                                   locales: list[str] | None = None) -> dict[str, dict]:
    """Build a brief per locale. Returns {locale_short: brief}."""
    if locales is None:
        locales = [m["locale_short"] for code, m in config_loader.markets().items()
                   if code != "US"]
    out: dict[str, dict] = {}
    for loc in locales:
        try:
            out[loc] = build_localization_brief(loc, master_brief, research, commercial)
        except Exception as e:
            print(f"      ⚠️  Localization brief for {loc} failed: {e}")
    print(f"   ✓ Built {len(out)} localization briefs")
    return out


if __name__ == "__main__":
    fake_master = {
        "topic": "best cycling sunglasses",
        "primary_keyword": "best cycling sunglasses",
        "search_intent": "commercial investigation",
    }
    fake_research = {"paa": {}, "serps": {"snapshots": []}}
    out = build_all_localization_briefs(fake_master, fake_research, None)
    print(f"\nGenerated {len(out)} briefs")
    print(json.dumps(out["nl"], indent=2, ensure_ascii=False))
