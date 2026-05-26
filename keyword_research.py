"""
DataForSEO keyword volume lookup for research_market_keywords().
=====================================
Endpoint used: keywords_data/google_ads/search_volume/live
Strategy: Claude Haiku picks the best local keyword per market; DataForSEO then
validates the exact monthly search volume for each selected keyword in one batch call.

Why search_volume/live (not keywords_for_keywords/live):
  keywords_for_keywords returns ideas in the seed keyword's language — passing an
  English seed to the DE endpoint returns almost no German results. search_volume/live
  takes any keyword in any language and returns its real volume for that locale.

Cost: ~$0.0005 per keyword per locale → ~€1/month for daily 11-locale lookups.
Credentials: DATAFORSEO_LOGIN (email) + DATAFORSEO_PASSWORD (API password)
Register: https://app.dataforseo.com/
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
LOCALE_GEO: dict[str, tuple[int, str]] = {
    "en":    (2840, "en"),   # United States
    "de":    (2276, "de"),   # Germany
    "nl":    (2528, "nl"),   # Netherlands
    "fr":    (2250, "fr"),   # France
    "es":    (2724, "es"),   # Spain
    "it":    (2380, "it"),   # Italy
    "da":    (2208, "da"),   # Denmark
    "nb":    (2578, "no"),   # Norway
    "pl":    (2616, "pl"),   # Poland
    "pt-PT": (2620, "pt"),   # Portugal
    "sv":    (2752, "sv"),   # Sweden
}


def get_search_volumes(locale_keywords: dict[str, str]) -> dict[str, int]:
    """
    Look up the exact monthly search volume for a specific keyword in each locale.
    Makes one request per locale (search_volume/live does not support multi-locale batching).

    Args:
        locale_keywords: {"de": "beste Fahrradbrillen", "nl": "beste fietsbrillen", ...}

    Returns:
        {"de": 170, "nl": 480, "fr": 260, ...}
        Returns {} if credentials missing or API call fails (caller handles gracefully).
    """
    if not DATAFORSEO_LOGIN or not DATAFORSEO_PASS:
        return {}

    out: dict[str, int] = {}

    for loc, kw in locale_keywords.items():
        if loc not in LOCALE_GEO or not kw:
            continue
        loc_code, lang_code = LOCALE_GEO[loc]
        try:
            r = requests.post(
                f"{BASE}/keywords_data/google_ads/search_volume/live",
                json=[{
                    "keywords":      [kw.lower()],   # lowercase → more reliable match
                    "location_code": loc_code,
                    "language_code": lang_code,
                }],
                auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASS),
                timeout=30,
            )
            r.raise_for_status()
            task    = r.json().get("tasks", [{}])[0]
            results = task.get("result") or []
            vol     = results[0].get("search_volume") or 0 if results else 0
            out[loc] = vol
        except Exception:
            out[loc] = 0   # non-fatal: log nothing, caller prints summary

    return out


if __name__ == "__main__":
    import json
    print("Testing DataForSEO search_volume/live")
    print(f"Credentials set: {bool(DATAFORSEO_LOGIN and DATAFORSEO_PASS)}\n")

    # Simulate what research_market_keywords() would pass after Haiku runs
    test_keywords = {
        "en": "best cycling glasses",
        "de": "beste Fahrradbrillen",
        "nl": "beste fietsbrillen",
        "fr": "meilleurs lunettes vélo",
        "es": "mejores gafas ciclismo",
        "it": "migliori occhiali ciclismo",
        "da": "bedste cykelbriller",
        "nb": "beste sykkelbriller",
        "pl": "najlepsze okulary rowerowe",
        "pt-PT": "melhores óculos de ciclismo",
        "sv": "bästa cykelglasögon",
    }

    try:
        volumes = get_search_volumes(test_keywords)
        print(json.dumps(volumes, indent=2, ensure_ascii=False))
        total = sum(volumes.values())
        print(f"\nTotal monthly searches across all markets: {total:,}")
    except Exception as e:
        print(f"Error: {e}")
