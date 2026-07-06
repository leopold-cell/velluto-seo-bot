"""
Site-wide technical SEO + GEO (Generative-Engine-Optimization) audit.

Technical/on-page checks run with plain requests + regex (no extra deps, same
style as the rest of the codebase). The GEO assessment — how citeable/answerable
the content is for AI answer engines (AI Overviews, ChatGPT) — is synthesised by
Claude (Sonnet), reusing the analysis pattern from seo_optimizer.
"""
from __future__ import annotations

import re

from review._common import (SITE, SONNET, SHOP_LOCALES, complete, http_get,
                            parse_json_block, have_anthropic)


def _text_between(html: str, pattern: str) -> str | None:
    m = re.search(pattern, html, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def check_page(url: str) -> dict:
    """Technical on-page SEO signals for a single URL."""
    r = http_get(url)
    if r is None or r.status_code != 200:
        return {"url": url, "ok": False, "status": (r.status_code if r else None)}
    html = r.text
    title = _text_between(html, r"<title[^>]*>(.*?)</title>")
    meta_desc = None
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, re.I)
    if m:
        meta_desc = m.group(1).strip()
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    cm = (re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
          or re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']', html, re.I))
    canonical = bool(cm)
    canonical_href = cm.group(1) if cm else None
    hreflangs = set(re.findall(r'<link[^>]+rel=["\']alternate["\'][^>]+hreflang=["\']([^"\']+)["\']', html, re.I))
    ld_types = re.findall(r'"@type"\s*:\s*"([^"]+)"', html)
    img_total = len(re.findall(r"<img\b", html, re.I))
    img_no_alt = len(re.findall(r'<img\b(?![^>]*\balt=)[^>]*>', html, re.I))
    internal_links = len(re.findall(r'href=["\'](?:https?://velluto-shop\.com)?/[^"\']*["\']', html, re.I))

    issues = []
    if not title or len(title) > 65:
        issues.append(f"title length {len(title or '')} (want ≤65)")
    if not meta_desc or len(meta_desc) > 160:
        issues.append(f"meta description {'missing' if not meta_desc else len(meta_desc)} (want ≤160)")
    if len(h1s) != 1:
        issues.append(f"{len(h1s)} H1 tags (want exactly 1)")
    if not canonical:
        issues.append("no canonical tag")
    elif canonical_href.rstrip("/") != url.rstrip("/"):
        # Pages in an hreflang set MUST self-canonicalize. A cross-locale
        # canonical (e.g. /de/… pointing at the EN root) breaks hreflang and
        # triggers GSC "Duplicate, Google chose different canonical than user".
        issues.append(f"canonical not self-referencing: {canonical_href}")
    if 'l.rel="canonical"' in html:
        # Regression guard: seo_bot used to inject a client-side JS canonical
        # into article bodies (removed Jul 2026) — it must never come back.
        issues.append("JS-injected canonical found in body (conflicts with Shopify's head canonical)")
    if img_no_alt:
        issues.append(f"{img_no_alt}/{img_total} images missing alt")
    missing_hreflang = [loc for loc in SHOP_LOCALES if not any(h.lower().startswith(loc.lower()) for h in hreflangs)]
    if missing_hreflang:
        issues.append(f"hreflang missing for: {', '.join(missing_hreflang)}")

    return {
        "url": url, "ok": True, "status": 200,
        "title": title, "title_len": len(title or ""),
        "meta_description_len": len(meta_desc or ""),
        "h1_count": len(h1s),
        "canonical": canonical,
        "canonical_href": canonical_href,
        "hreflang_locales": sorted(hreflangs),
        "structured_data_types": sorted(set(ld_types)),
        "images": {"total": img_total, "missing_alt": img_no_alt},
        "internal_links": internal_links,
        "issues": issues,
    }


def _technical(sample_article_urls: list[str]) -> dict:
    pages = {
        "home": f"{SITE}/",
        "collection": f"{SITE}/collections/velluto-stradapro-cycling-glasses",
        "blog": f"{SITE}/blogs/velluto-the-magazine",
    }
    results = {name: check_page(url) for name, url in pages.items()}
    for i, url in enumerate(sample_article_urls[:3]):
        results[f"article_{i+1}"] = check_page(url)

    robots = http_get(f"{SITE}/robots.txt")
    sitemap = http_get(f"{SITE}/sitemap.xml")
    return {
        "pages": results,
        "robots_txt": bool(robots and robots.status_code == 200),
        "sitemap_xml": bool(sitemap and sitemap.status_code == 200),
        "sitemap_references_articles": bool(sitemap and "blogs" in (sitemap.text or "")),
    }


_GEO_SYSTEM = (
    "You are a GEO (Generative-Engine-Optimization) strategist. GEO = optimizing "
    "for AI answer engines (Google AI Overviews, ChatGPT, Perplexity). Given a "
    "site's technical SEO summary and a sample of article HTML, assess how likely "
    "this content is to be CITED by AI engines and how to improve it. Return ONLY "
    'JSON: {"geo_score":0-100,"seo_score":0-100,"top_geo_gaps":["..."],'
    '"top_seo_fixes":["..."],"quick_wins":["..."]}. Consider: clear sourceable '
    "answer blocks, FAQ/Q&A schema, concise definitional summaries, entity clarity, "
    "comparison tables, structured data (Article/FAQ/Product), freshness, citations."
)


def _llm_geo(technical: dict, sample_html: str) -> dict | None:
    if not have_anthropic():
        return None
    import json as _json
    user = ("TECHNICAL SUMMARY:\n" + _json.dumps(technical, default=str)[:6000]
            + "\n\nSAMPLE ARTICLE HTML (truncated):\n" + (sample_html or "")[:8000])
    out = complete(_GEO_SYSTEM, user, model=SONNET, max_tokens=900)
    parsed = parse_json_block(out)
    return parsed if isinstance(parsed, dict) else None


def audit(articles: list[dict]) -> dict:
    sample_urls = [a["url"] for a in articles[:3]]
    technical = _technical(sample_urls)
    sample_html = articles[0]["body_html"] if articles else ""
    geo = _llm_geo(technical, sample_html)
    all_issues = []
    for name, page in technical["pages"].items():
        for iss in page.get("issues", []):
            all_issues.append(f"{name}: {iss}")
    if not technical["robots_txt"]:
        all_issues.append("robots.txt not reachable")
    if not technical["sitemap_xml"]:
        all_issues.append("sitemap.xml not reachable")
    return {
        "technical": technical,
        "technical_issues": all_issues,
        "geo": geo,
    }
