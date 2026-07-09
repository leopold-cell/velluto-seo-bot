#!/usr/bin/env python3
"""
Velluto CTR Optimizer — closes the "detect → rewrite → measure" loop.

The bot detects low-CTR opportunities (seo_optimizer) but nothing ever
rewrote the SERP snippet of an EXISTING page. This step does exactly that:

1. DETECT   — pull 28d GSC per-page data; flag blog articles whose CTR is
              far below the benchmark for their avg. position (e.g. the
              Oakley-alternative article: 7.5k impressions at 0.2% on pos 6).
2. REWRITE  — Claude Haiku writes a click-worthy SEO title + meta description
              from the page's REAL top queries. Written to the global
              title_tag / description_tag metafields — the visible H1,
              article title and handle/URL stay untouched.
3. MEASURE  — after the cooldown, the next runs compare the page's CTR vs.
              the snapshot taken at rewrite time and log the outcome.

Guardrails: max 2 pages/day, 14-day cooldown per page, full before/after
log in data/ctr_optimizer_state.json (committed by the daily cron).

Runs daily via run.sh; every external dependency fails soft (no crash of
the chain). Manual: python3 ctr_optimizer.py [--dry-run]
"""
import datetime
import json
import os
import re
import sys

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE, ".env"), override=True)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID       = os.getenv("BLOG_ID", "127785959765")
HEADERS       = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

GSC_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GSC_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GSC_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN", "")
GSC_SITE_URL      = os.getenv("GSC_SITE_URL", "sc-domain:velluto-shop.com")

STATE_PATH   = os.path.join(BASE, "data", "ctr_optimizer_state.json")
SITE         = "https://velluto-shop.com"
BLOG_PREFIX  = f"{SITE}/blogs/"           # root-locale articles only; locales
                                          # inherit via canonical/hreflang
MAX_PER_DAY      = 2
COOLDOWN_DAYS    = 14
MIN_IMPRESSIONS  = 300    # 28d window
HAIKU            = "claude-haiku-4-5-20251001"

DRY_RUN = "--dry-run" in sys.argv


# ── benchmarks ───────────────────────────────────────────────────────────────

def expected_ctr(position: float) -> float:
    """Rough organic CTR benchmark (%) by average position."""
    if position <= 3:
        return 5.0
    if position <= 5:
        return 3.0
    if position <= 10:
        return 1.5
    return 0.8


# ── GSC ──────────────────────────────────────────────────────────────────────

def _gsc_token() -> str | None:
    if not (GSC_CLIENT_ID and GSC_CLIENT_SECRET and GSC_REFRESH_TOKEN):
        return None
    try:
        r = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": GSC_CLIENT_ID, "client_secret": GSC_CLIENT_SECRET,
            "refresh_token": GSC_REFRESH_TOKEN, "grant_type": "refresh_token",
        }, timeout=20)
        return r.json().get("access_token")
    except Exception:
        return None


def _gsc_query(token: str, body: dict) -> list[dict]:
    r = requests.post(
        f"https://searchconsole.googleapis.com/webmasters/v3/sites/{GSC_SITE_URL}"
        "/searchAnalytics/query",
        headers={"Authorization": f"Bearer {token}"}, json=body, timeout=30)
    r.raise_for_status()
    return r.json().get("rows", [])


def fetch_pages(token: str) -> list[dict]:
    today = datetime.date.today()
    return _gsc_query(token, {
        "startDate": (today - datetime.timedelta(days=28)).isoformat(),
        "endDate":   today.isoformat(),
        "dimensions": ["page"],
        "rowLimit":  250,
    })


def fetch_page_queries(token: str, url: str, limit: int = 10) -> list[dict]:
    today = datetime.date.today()
    return _gsc_query(token, {
        "startDate": (today - datetime.timedelta(days=28)).isoformat(),
        "endDate":   today.isoformat(),
        "dimensions": ["query"],
        "dimensionFilterGroups": [{"filters": [
            {"dimension": "page", "operator": "equals", "expression": url}]}],
        "rowLimit": limit,
    })


# ── candidate selection (pure — unit-testable) ───────────────────────────────

def select_candidates(rows: list[dict], state: dict,
                      today: datetime.date | None = None) -> list[dict]:
    """Blog pages whose CTR is < 50% of the positional benchmark, ranked by
    missed clicks. Excludes pages inside the cooldown window."""
    today = today or datetime.date.today()
    out = []
    for row in rows:
        url = (row.get("keys") or [""])[0]
        if not url.startswith(BLOG_PREFIX) or "/tagged/" in url:
            continue
        impressions = int(row.get("impressions", 0))
        if impressions < MIN_IMPRESSIONS:
            continue
        pos = float(row.get("position", 99))
        ctr = float(row.get("ctr", 0)) * 100
        bench = expected_ctr(pos)
        if ctr >= bench * 0.5:
            continue
        entry = state.get(url) or {}
        last = entry.get("last_optimized")
        if last:
            try:
                age = (today - datetime.date.fromisoformat(last)).days
                if age < COOLDOWN_DAYS:
                    continue
            except Exception:
                pass
        out.append({
            "url": url, "impressions": impressions, "ctr": round(ctr, 2),
            "position": round(pos, 1), "benchmark": bench,
            "missed_clicks": round(impressions * (bench - ctr) / 100),
        })
    out.sort(key=lambda c: c["missed_clicks"], reverse=True)
    return out


# ── Shopify ──────────────────────────────────────────────────────────────────

def article_by_handle(handle: str) -> dict | None:
    try:
        r = requests.get(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json",
            params={"handle": handle, "fields": "id,title,handle"},
            headers=HEADERS, timeout=20)
        arts = r.json().get("articles", [])
        return arts[0] if arts else None
    except Exception:
        return None


def upsert_metafield(article_id: int, key: str, value: str, max_len: int) -> bool:
    """Create-or-update a global.<key> metafield on a blog article."""
    base = f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{article_id}/metafields.json"
    payload = {"metafield": {"namespace": "global", "key": key,
                             "value": value[:max_len],
                             "type": "single_line_text_field"}}
    r = requests.post(base, headers=HEADERS, json=payload, timeout=15)
    if r.status_code == 201:
        return True
    if r.status_code == 422:  # exists → PUT
        mfs = requests.get(f"{base.split('.json')[0]}.json?namespace=global&key={key}",
                           headers=HEADERS, timeout=15).json().get("metafields", [])
        if mfs:
            mid = mfs[0]["id"]
            r2 = requests.put(
                f"https://{SHOPIFY_STORE}/admin/api/2024-01/metafields/{mid}.json",
                headers=HEADERS,
                json={"metafield": {"id": mid, "value": value[:max_len]}}, timeout=15)
            return r2.status_code == 200
    return False


# ── rewrite ──────────────────────────────────────────────────────────────────

def _clip_words(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(" ,;:-–|") or s[:n]


def generate_snippet(client: Anthropic, title: str, queries: list[dict],
                     cand: dict) -> dict | None:
    q_lines = "\n".join(
        f"- \"{q['keys'][0]}\" — {int(q.get('impressions',0))} impressions, "
        f"pos {q.get('position',0):.1f}, {q.get('clicks',0)} clicks"
        for q in queries[:10]) or "- (no query data)"
    r = client.messages.create(
        model=HAIKU, max_tokens=300,
        system="You are an SEO copywriter. Return ONLY valid JSON, no extra text.",
        messages=[{"role": "user", "content":
            f"This blog article ranks on Google (avg pos {cand['position']}) but its "
            f"snippet only wins {cand['ctr']}% CTR — the benchmark for that position is "
            f"{cand['benchmark']}%. Rewrite the SERP snippet to WIN THE CLICK.\n\n"
            f"Current title: {title}\n"
            f"Real queries it ranks for (28d):\n{q_lines}\n\n"
            "Rules:\n"
            "- seo_title: max 60 chars, top query's core terms FIRST, then a concrete "
            "hook (number, year, outcome). No clickbait, no ALL CAPS, no emoji.\n"
            "- meta_description: max 155 chars, answers the searcher's intent, ends "
            "with a reason to click. Same language as the queries.\n\n"
            'Return: {"seo_title": "...", "meta_description": "..."}'}],
    )
    raw = r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    try:
        data = json.loads(raw)
        seo_title = _clip_words(data.get("seo_title", ""), 60)
        meta_desc = (data.get("meta_description") or "").strip()[:155]
        if not seo_title or not meta_desc:
            return None
        return {"seo_title": seo_title, "meta_description": meta_desc}
    except Exception:
        return None


# ── state + measurement ──────────────────────────────────────────────────────

def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def measure_past_rewrites(state: dict, rows: list[dict]) -> None:
    """After the cooldown, compare current CTR vs. the rewrite-time snapshot."""
    today = datetime.date.today()
    by_url = {(r.get("keys") or [""])[0]: r for r in rows}
    for url, entry in state.items():
        if entry.get("measured") or not entry.get("last_optimized"):
            continue
        try:
            age = (today - datetime.date.fromisoformat(entry["last_optimized"])).days
        except Exception:
            continue
        if age < COOLDOWN_DAYS:
            continue
        row = by_url.get(url)
        if not row:
            continue
        ctr_now = round(float(row.get("ctr", 0)) * 100, 2)
        before  = entry.get("before", {}).get("ctr", 0)
        entry["measured"] = {
            "date": today.isoformat(), "ctr_before": before, "ctr_after": ctr_now,
            "outcome": "improved" if ctr_now > before else "no_lift",
        }
        icon = "🟢" if ctr_now > before else "🔴"
        print(f"   {icon} Measured {url.split('/')[-1][:40]}: "
              f"CTR {before}% → {ctr_now}% after {age}d")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n🎯 Velluto CTR Optimizer — {datetime.date.today()}")
    if not SHOPIFY_TOKEN:
        print("   SHOPIFY_TOKEN missing — skipping")
        return
    token = _gsc_token()
    if not token:
        print("   GSC credentials missing — skipping")
        return

    try:
        rows = fetch_pages(token)
    except Exception as e:
        print(f"   ⚠️  GSC fetch failed: {e} — skipping")
        return

    state = load_state()
    measure_past_rewrites(state, rows)

    candidates = select_candidates(rows, state)
    if not candidates:
        print("   ✓ No low-CTR candidates above thresholds — nothing to do")
        save_state(state)
        return
    print(f"   {len(candidates)} candidate(s); taking top {MAX_PER_DAY}:")
    for c in candidates[:MAX_PER_DAY]:
        print(f"   → {c['url'].split('/')[-1][:48]} | {c['impressions']:,} impr | "
              f"CTR {c['ctr']}% vs bench {c['benchmark']}% | pos {c['position']} | "
              f"~{c['missed_clicks']} missed clicks")

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    done = 0
    for cand in candidates[:MAX_PER_DAY]:
        handle = cand["url"].rstrip("/").rsplit("/", 1)[-1]
        art = article_by_handle(handle)
        if not art:
            print(f"   ⚠️  no article for handle '{handle}' — skipping")
            continue
        queries = []
        try:
            queries = fetch_page_queries(token, cand["url"])
        except Exception:
            pass
        snippet = generate_snippet(client, art.get("title", ""), queries, cand)
        if not snippet:
            print(f"   ⚠️  snippet generation failed for '{handle}' — skipping")
            continue

        print(f"   ✏️  {handle}")
        print(f"      title: {snippet['seo_title']}")
        print(f"      meta:  {snippet['meta_description']}")
        if DRY_RUN:
            print("      (dry-run — not written)")
            continue

        ok_t = upsert_metafield(art["id"], "title_tag", snippet["seo_title"], 60)
        ok_m = upsert_metafield(art["id"], "description_tag", snippet["meta_description"], 155)
        if not (ok_t and ok_m):
            print(f"      ❌ metafield write failed (title={ok_t}, meta={ok_m})")
            continue

        state[cand["url"]] = {
            "last_optimized": datetime.date.today().isoformat(),
            "article_id": art["id"],
            "before": {"ctr": cand["ctr"], "position": cand["position"],
                       "impressions": cand["impressions"],
                       "title": art.get("title", "")},
            "seo_title": snippet["seo_title"],
            "meta_description": snippet["meta_description"],
            "measured": None,
        }
        done += 1
        print("      ✅ SERP snippet updated (title_tag + description_tag)")

    if not DRY_RUN:
        save_state(state)
    print(f"   Done — {done} page(s) optimized today (cap {MAX_PER_DAY}, "
          f"cooldown {COOLDOWN_DAYS}d)")


if __name__ == "__main__":
    main()
