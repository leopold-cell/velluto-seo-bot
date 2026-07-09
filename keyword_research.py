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

Cost (IMPORTANT — learned the hard way, Jul 2026): DataForSEO bills live
search_volume PER TASK (~$0.05), not per keyword, and every locale needs its own
task (one location/language per task). 11 locales/article × up to 4 articles/day
in peak season burned ~$5-6/day. Three guards keep this cheap now:
  1. 90-day cache per (locale, keyword) in data/keyword_volume_cache.json —
     volumes barely move, so repeat lookups are free. The file is committed by
     the daily cron, so the cache survives re-clones.
  2. All cache misses go out as ONE batched HTTP request (one task per locale);
     falls back to per-locale single requests if the batch call fails.
  3. DATAFORSEO_DAILY_TASK_CAP (default 40 tasks/day ≈ $2 worst case) — beyond
     the cap, lookups return volume 0, which every caller handles gracefully.
Credentials: DATAFORSEO_LOGIN (email) + DATAFORSEO_PASSWORD (API password)
Register: https://app.dataforseo.com/
"""
import datetime
import json
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

CACHE_PATH     = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "data", "keyword_volume_cache.json")
CACHE_TTL_DAYS = 90
DAILY_TASK_CAP = int(os.getenv("DATAFORSEO_DAILY_TASK_CAP", "40"))

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


# ── cache helpers ────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
    except Exception:
        pass  # cache is an optimization — never let it break the lookup


def _cache_key(loc: str, kw: str) -> str:
    return f"{loc}|{kw.strip().lower()}"


def _fresh(entry: dict, today: datetime.date) -> bool:
    try:
        age = (today - datetime.date.fromisoformat(entry["date"])).days
        return 0 <= age <= CACHE_TTL_DAYS
    except Exception:
        return False


def _tasks_used_today(cache: dict, today: str) -> int:
    return int((cache.get("_meta") or {}).get("tasks", {}).get(today, 0))


def _count_tasks(cache: dict, today: str, n: int) -> None:
    meta = cache.setdefault("_meta", {})
    # keep only today's counter — no point carrying history in every commit
    meta["tasks"] = {today: _tasks_used_today(cache, today) + n}


# ── API ──────────────────────────────────────────────────────────────────────

def _parse_task_volume(task: dict) -> int:
    results = task.get("result") or []
    return (results[0].get("search_volume") or 0) if results else 0


def _fetch_batch(misses: list[tuple[str, str]]) -> dict[str, int]:
    """One HTTP request with one task per locale. Raises on transport errors."""
    payload = []
    for loc, kw in misses:
        loc_code, lang_code = LOCALE_GEO[loc]
        payload.append({
            "keywords":      [kw.lower()],   # lowercase → more reliable match
            "location_code": loc_code,
            "language_code": lang_code,
        })
    r = requests.post(
        f"{BASE}/keywords_data/google_ads/search_volume/live",
        json=payload,
        auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASS),
        timeout=60,
    )
    r.raise_for_status()
    tasks = r.json().get("tasks") or []
    if len(tasks) != len(misses):
        raise ValueError(f"batch returned {len(tasks)} tasks for {len(misses)} sent")
    return {loc: _parse_task_volume(task) for (loc, _), task in zip(misses, tasks)}


def _fetch_single(loc: str, kw: str) -> int:
    loc_code, lang_code = LOCALE_GEO[loc]
    r = requests.post(
        f"{BASE}/keywords_data/google_ads/search_volume/live",
        json=[{
            "keywords":      [kw.lower()],
            "location_code": loc_code,
            "language_code": lang_code,
        }],
        auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASS),
        timeout=30,
    )
    r.raise_for_status()
    return _parse_task_volume(r.json().get("tasks", [{}])[0])


def get_search_volumes(locale_keywords: dict[str, str]) -> dict[str, int]:
    """
    Look up the exact monthly search volume for a specific keyword in each locale.
    Cache-first (90d TTL); cache misses go out as ONE batched request (one task
    per locale, billing is per task either way); hard daily task cap.

    Args:
        locale_keywords: {"de": "beste Fahrradbrillen", "nl": "beste fietsbrillen", ...}

    Returns:
        {"de": 170, "nl": 480, "fr": 260, ...}
        Returns {} if credentials missing; missing/capped lookups return 0
        (caller handles gracefully).
    """
    if not DATAFORSEO_LOGIN or not DATAFORSEO_PASS:
        return {}

    today_d = datetime.date.today()
    today   = today_d.isoformat()
    cache   = _load_cache()

    out: dict[str, int] = {}
    misses: list[tuple[str, str]] = []
    for loc, kw in locale_keywords.items():
        if loc not in LOCALE_GEO or not kw:
            continue
        entry = cache.get(_cache_key(loc, kw))
        if isinstance(entry, dict) and _fresh(entry, today_d):
            out[loc] = int(entry.get("volume", 0))
        else:
            misses.append((loc, kw))

    if not misses:
        return out

    # Daily cost cap: each miss = one billable task (~$0.05).
    used   = _tasks_used_today(cache, today)
    budget = max(0, DAILY_TASK_CAP - used)
    if budget < len(misses):
        skipped = misses[budget:]
        misses  = misses[:budget]
        for loc, _ in skipped:
            out[loc] = 0
        print(f"   ⚠️  DataForSEO daily task cap reached "
              f"({used}/{DAILY_TASK_CAP}) — {len(skipped)} lookup(s) skipped (volume=0)")

    fetched: dict[str, int] = {}
    if misses:
        try:
            fetched = _fetch_batch(misses)
        except Exception:
            # batch endpoint hiccup → old per-locale behaviour
            for loc, kw in misses:
                try:
                    fetched[loc] = _fetch_single(loc, kw)
                except Exception:
                    fetched[loc] = 0
        _count_tasks(cache, today, len(misses))
        kw_by_loc = dict(misses)
        for loc, vol in fetched.items():
            out[loc] = vol
            cache[_cache_key(loc, kw_by_loc[loc])] = {"volume": vol, "date": today}
        _save_cache(cache)

    return out


if __name__ == "__main__":
    print("Testing DataForSEO search_volume/live (cache-first, batched, capped)")
    print(f"Credentials set: {bool(DATAFORSEO_LOGIN and DATAFORSEO_PASS)}")
    print(f"Cache: {CACHE_PATH} | TTL {CACHE_TTL_DAYS}d | daily task cap {DAILY_TASK_CAP}\n")

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
