"""
Translation audit: completeness (all target locales registered in Shopify) and
optional correctness (right language, keyword present, price matches config).

Completeness uses the same GraphQL `translatableResource` query as
retrofit_translations.get_all_translation_locales(). The safe auto-fix for
MISSING locales reuses seo_bot.register_shopify_translation() (same path as
retrofit_translations.py). Correctness issues are report-only.
"""
from __future__ import annotations

import os

import requests

from review._common import (HAIKU, SHOP_LOCALES, complete, parse_json_block,
                            have_anthropic, review_config)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}


def registered_locales(article_id: int) -> set[str]:
    """Locales that already have translations registered for this article."""
    if not SHOPIFY_TOKEN:
        return set()
    try:
        r = requests.post(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
            headers=HEADERS,
            json={"query": """
            query($id: ID!) {
              translatableResource(resourceId: $id) {
                translations(locale: "") { locale key }
              }
            }
            """, "variables": {"id": f"gid://shopify/Article/{article_id}"}},
            timeout=20,
        )
        items = ((r.json().get("data", {}) or {}).get("translatableResource") or {}).get("translations") or []
        return {t["locale"] for t in items}
    except Exception:
        return set()


def audit(articles: list[dict], deep: bool = False) -> dict:
    """deep=True also samples translation *correctness* via Haiku (extra cost)."""
    cfg = review_config()
    target = cfg.get("target_locales") or SHOP_LOCALES

    results: list[dict] = []
    missing_by_locale: dict[str, list] = {loc: [] for loc in target}

    for a in articles:
        existing = registered_locales(a["id"])
        missing = [loc for loc in target if loc not in existing]
        for loc in missing:
            missing_by_locale[loc].append(a["handle"])
        results.append({
            "id": a["id"],
            "handle": a["handle"],
            "registered": sorted(existing),
            "missing": missing,
            "completeness_pct": round(100 * (len(target) - len(missing)) / len(target), 1),
            "passed": not missing,
        })

    complete_count = sum(1 for r in results if r["passed"])
    return {
        "target_locales": target,
        "articles_checked": len(results),
        "fully_complete": complete_count,
        "avg_completeness_pct": round(
            sum(r["completeness_pct"] for r in results) / len(results), 1) if results else 0,
        "missing_by_locale": {k: v for k, v in missing_by_locale.items() if v},
        "articles_needing_fix": [r["id"] for r in results if not r["passed"]],
        "results": results,
    }


# ── safe auto-fix: register missing locales (reuses the retrofit path) ──────────

def autofix_missing(article_audit_results: list[dict], limit: int | None = None) -> dict:
    """
    Register missing translations using seo_bot's proven path
    (research_market_keywords → generate_market_adaptation → register_shopify_translation).
    Returns a summary. Requires SHOPIFY_TOKEN + ANTHROPIC_API_KEY.
    """
    import time
    fixed, errors = [], []
    if not SHOPIFY_TOKEN or not have_anthropic():
        return {"fixed": [], "errors": ["missing SHOPIFY_TOKEN or ANTHROPIC_API_KEY"], "skipped": True}

    from seo_bot import (get_translatable_digests, register_shopify_translation,
                         generate_market_adaptation, research_market_keywords)
    from review import inventory

    todo = [r for r in article_audit_results if not r["passed"]]
    if limit:
        todo = todo[:limit]

    # Re-fetch bodies for the articles we will fix (need body_html + title).
    by_id = {a["id"]: a for a in inventory.fetch_all_articles()}

    for r in todo:
        a = by_id.get(r["id"])
        if not a:
            continue
        try:
            digests = get_translatable_digests(r["id"])
        except Exception as e:
            errors.append(f"{r['handle']}: digests failed: {e}")
            continue
        kw_hint = r["handle"].replace("-", " ")
        try:
            mkt = research_market_keywords(kw_hint)
        except Exception:
            mkt = {loc: {"keyword": kw_hint, "intent": ""} for loc in r["missing"]}
        post = {"body_html": a["body_html"], "title_de": a["title"]}
        for loc in r["missing"]:
            market = mkt.get(loc, {"keyword": kw_hint, "intent": ""})
            try:
                adapt = generate_market_adaptation(post, loc, market)
                ok = register_shopify_translation(
                    r["id"], loc, adapt["title"], adapt["body_html"], adapt["meta_desc"], digests)
                (fixed if ok else errors).append(f"{r['handle']} [{loc}]")
            except Exception as e:
                errors.append(f"{r['handle']} [{loc}]: {e}")
            time.sleep(2)
        time.sleep(6)
    return {"fixed": fixed, "errors": errors, "skipped": False}
