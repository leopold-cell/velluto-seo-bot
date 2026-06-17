"""
Fetch all bot-published blog articles for the review.

Mirrors retrofit_translations.get_all_articles() (REST pagination) but enriches
each record with a public URL and word_count, and filters to bot articles
(identified by the .vl CSS class the magazine template injects).
"""
from __future__ import annotations

import os
import re

import requests

from review._common import BLOG_HANDLE, SITE

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID = os.getenv("BLOG_ID", "127785959765")
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def fetch_all_articles() -> list[dict]:
    """Return all published articles with id, title, handle, url, body_html,
    published_at, word_count. Empty list if no Shopify token."""
    if not SHOPIFY_TOKEN:
        return []
    arts: list[dict] = []
    page_info = None
    while True:
        params = {"limit": 250,
                  "fields": "id,title,handle,body_html,published_at,updated_at,tags,summary_html"}
        if page_info:
            params["page_info"] = page_info
        r = requests.get(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json",
            params=params, headers=HEADERS, timeout=20,
        )
        for a in r.json().get("articles", []):
            body = a.get("body_html", "") or ""
            arts.append({
                "id": a.get("id"),
                "title": a.get("title", ""),
                "handle": a.get("handle", ""),
                "url": f"{SITE}/blogs/{BLOG_HANDLE}/{a.get('handle','')}",
                "body_html": body,
                "summary_html": a.get("summary_html", "") or "",
                "tags": [t.strip() for t in (a.get("tags") or "").split(",") if t.strip()],
                "published_at": a.get("published_at"),
                "updated_at": a.get("updated_at"),
                "word_count": len(_strip_html(body).split()),
            })
        link = r.headers.get("Link", "")
        if 'rel="next"' in link:
            m = re.search(r'page_info=([^&>]+)[^>]*>;\s*rel="next"', link)
            page_info = m.group(1) if m else None
            if not page_info:
                break
        else:
            break
    return arts


def is_bot_article(article: dict) -> bool:
    """Bot articles carry the .vl CSS class (same heuristic as retrofit/strip scripts)."""
    return 'class="vl"' in (article.get("body_html") or "")


def primary_keyword(article: dict) -> str:
    """Best-effort primary keyword: first tag, else the title."""
    tags = article.get("tags") or []
    if tags:
        return tags[0]
    return article.get("title", "")
