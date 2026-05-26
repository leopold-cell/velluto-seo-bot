"""
DataForSEO keyword volume lookup for research_market_keywords().
=====================================
Endpoint: keywords_data/google_ads/keywords_for_keywords/live
Batches all locales in a single HTTP call — no extra pip dependency (uses requests).

Cost: ~$0.0005 per keyword per locale → ~€1/month for daily 11-locale lookups.
Credentials: DATAFORSEO_LOGIN (email) + DATAFORSEO_PASSWORD (API password)
Register: https://app.dataforseo.com/

Graceful degradation: returns {} if credentials missing or API call fails.
Caller (research_market_keywords) falls back to Haiku-only in that case.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv(
    dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    override=True,
)

DATAFORSEO_LOGIN = os.getenv("DATAFORSEO_LOGIN", "")
DATAFORSEO_PASS  = os.getenv("DATAFORSEO_PASSWORD", "")
BASE             = "https://api.dataforseo.com/v3"

# locale → (location_code, language_code) for Google Ads API
# location_codes: https://api.dataforseo.com/v3/keywords_data/google_ads/locations
# language_codes: https://api.dataforseo.com/v3/keywords_data/google_ads/languages
LOCALE_GEO: dict[str, tuple[int, str]] = {
    "en":    (2840, "en"),   # United States
    "de":    (2276, "de"),   # Germany
    "nl":    (2528, "nl"),   # Netherlands
    "fr":    (2250, "fr"),   # France
    "es":    (2724, "es"),   # Spain
    "it":    (2380, "it"),   # Italy
    "da":    (2208, "da"),   # Denmark
    "nb":    (2578, "no"),   # Norway (language code "no" for Norwegian)
    "pl":    (2616, "pl"),   # Poland
    "pt-PT": (2620, "pt"),   # Portugal
    "sv":    (2752, "sv"),   # Sweden
}


def get_keyword_ideas(
    seed_keyword: str,
    locales: list[str],
    n: int = 5,
) -> dict[str, list[dict]]:
    """
    Fetch keyword ideas + search volumes from DataForSEO for all requested locales.
    All locales are batched into a single HTTP call.

    Returns:
        {
            "de": [{"keyword": "beste Fahrradbrillen", "volume": 1200}, ...],
            "nl": [...],
            ...
        }
    Returns {} on missing credentials or API failure — caller handles gracefully.
    """
    if not DATAFORSEO_LOGIN or not DATAFORSEO_PASS:
        return {}

    tasks: list[dict] = []
    locale_order: list[str] = []

    for loc in locales:
        if loc not in LOCALE_GEO:
            continue
        loc_code, lang_code = LOCALE_GEO[loc]
        tasks.append({
            "keywords":      [seed_keyword],
            "location_code": loc_code,
            "language_code": lang_code,
            "limit":         n,
            "order_by":      ["search_volume,desc"],
        })
        locale_order.append(loc)

    if not tasks:
        return {}

    try:
        r = requests.post(
            f"{BASE}/keywords_data/google_ads/keywords_for_keywords/live",
            json=tasks,
            auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASS),
            timeout=60,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"DataForSEO request failed: {exc}") from exc

    out: dict[str, list[dict]] = {}
    for i, task in enumerate(r.json().get("tasks", [])):
        if i >= len(locale_order):
            break
        locale  = locale_order[i]
        results = task.get("result") or []
        items   = results[0].get("items") or [] if results else []
        out[locale] = [
            {
                "keyword": item["keyword"],
                "volume":  item.get("search_volume") or 0,
            }
            for item in items
        ]
    return out


if __name__ == "__main__":
    import json
    test_locales = ["en", "de", "nl", "fr", "es"]
    print(f"Testing DataForSEO with seed: 'best cycling glasses'")
    print(f"Credentials set: {bool(DATAFORSEO_LOGIN and DATAFORSEO_PASS)}\n")
    try:
        result = get_keyword_ideas("best cycling glasses", test_locales, n=3)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")
