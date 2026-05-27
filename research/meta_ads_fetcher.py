"""
Meta Ads research signal (READ-ONLY).

Pulls Velluto's currently-active Meta ads via Marketing API. Extracts the creative
headlines, primary text and CTAs so the brief generator can align organic article
tone with paid messaging that's already working.

ENV REQUIRED:
  META_ACCESS_TOKEN     — Graph API token with 'ads_read' scope ONLY
                          (NO 'ads_management' — we never write)
  META_AD_ACCOUNT_ID    — Ad account ID, e.g. 'act_1234567890'

STRICTLY READ-ONLY:
  - Only HTTP GET requests
  - Never POST / PUT / DELETE to Meta Graph
  - Never write/mutate anything in Meta Ads Manager
  - If the token has write scope, we still only call read endpoints

Output: data/processed/meta_ads_snapshot.json
Failure mode: missing token / API error → returns {"skipped": true, ...} gracefully.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from collections import Counter

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(ROOT, ".env"), override=True)

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")
GRAPH_VERSION = "v22.0"
OUTPUT_PATH = os.path.join(ROOT, "data", "processed", "meta_ads_snapshot.json")
HTTP_TIMEOUT = 20
MAX_ADS_FETCHED = 50


def _fetch_active_ads() -> list[dict]:
    """GET ads with effective_status=ACTIVE + creative subfields. READ-ONLY."""
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{META_AD_ACCOUNT_ID}/ads"
    params = {
        "fields": "id,name,status,effective_status,creative{title,body,call_to_action_type,object_story_spec}",
        "filtering": json.dumps([
            {"field": "effective_status", "operator": "IN", "value": ["ACTIVE"]}
        ]),
        "limit": MAX_ADS_FETCHED,
        "access_token": META_ACCESS_TOKEN,
    }
    try:
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        if r.status_code == 400:
            # Common: bad token, ad account not authorized, scope missing
            try:
                err = r.json().get("error", {})
                print(f"      ⚠️  Meta Ads API 400: {err.get('message','?')} (code {err.get('code','?')})")
            except Exception:
                pass
            return []
        r.raise_for_status()
        return r.json().get("data", []) or []
    except Exception as e:
        print(f"      ⚠️  Meta Ads fetch failed: {e}")
        return []


def _extract_creative(ad: dict) -> dict | None:
    """Pull headline + body + CTA from the nested creative payload."""
    cr = ad.get("creative") or {}
    title = cr.get("title")
    body = cr.get("body")
    cta = cr.get("call_to_action_type")

    # Some ad types nest the copy under object_story_spec.link_data
    if not title or not body:
        oss = (cr.get("object_story_spec") or {})
        link_data = oss.get("link_data") or {}
        title = title or link_data.get("name")
        body = body or link_data.get("description") or link_data.get("message")
        if not cta:
            cta_data = link_data.get("call_to_action") or {}
            cta = cta_data.get("type")

    if not (title or body):
        return None
    return {
        "ad_id":    ad.get("id"),
        "ad_name":  ad.get("name"),
        "headline": (title or "").strip()[:200],
        "body":     (body or "").strip()[:500],
        "cta":      (cta or "").strip(),
    }


def _summarize_themes(creatives: list[dict]) -> str:
    """One-line summary of recurring themes across active creatives."""
    if not creatives:
        return ""
    headline_words = Counter()
    for c in creatives:
        for word in (c.get("headline","") + " " + c.get("body","")).lower().split():
            # Keep meaningful tokens only
            if len(word) >= 5 and word.isalpha():
                headline_words[word] += 1
    top = headline_words.most_common(8)
    if not top:
        return ""
    return "Most common terms in active creatives: " + ", ".join(f"{w}({n})" for w, n in top)


def run() -> dict:
    today = _dt.date.today().isoformat()

    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT_ID:
        result = {
            "date":     today,
            "skipped":  True,
            "reason":   "META_ACCESS_TOKEN or META_AD_ACCOUNT_ID missing in .env",
            "active_ads_count": 0,
            "creatives": [],
            "themes_summary": "",
        }
        _save(result)
        print(f"   Meta Ads: credentials missing — skipping (set META_ACCESS_TOKEN + META_AD_ACCOUNT_ID)")
        return result

    ads = _fetch_active_ads()
    creatives = []
    for ad in ads:
        c = _extract_creative(ad)
        if c:
            creatives.append(c)

    result = {
        "date":              today,
        "skipped":           False,
        "active_ads_count":  len(ads),
        "creatives_count":   len(creatives),
        "creatives":         creatives,
        "themes_summary":    _summarize_themes(creatives),
    }
    _save(result)
    print(f"   ✓ Meta Ads: {len(ads)} active ads, {len(creatives)} with extractable creative")
    return result


def _save(payload: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_latest() -> dict | None:
    """Read back the most-recent meta_ads_snapshot.json. Used by brief enrichment."""
    if not os.path.exists(OUTPUT_PATH):
        return None
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import sys
    res = run()
    print(json.dumps({k: v for k, v in res.items() if k != "creatives"}, indent=2))
    if res.get("creatives"):
        print(f"\nFirst creative sample:")
        print(json.dumps(res["creatives"][0], indent=2, ensure_ascii=False))
