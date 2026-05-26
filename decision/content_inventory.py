"""
Content inventory — list every existing Velluto Shopify article + collection page
with its URL, title, primary keyword, last update date.

Used by:
  - opportunity_scorer.py → cannibalization detection (don't propose topics
                            that duplicate an existing page's intent)
  - topic_selector.py     → "update_existing_article" candidates

Output: data/processed/existing_content_inventory.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(ROOT, ".env"), override=True)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "")
BLOG_ID       = os.getenv("BLOG_ID", "")
OUTPUT_PATH   = os.path.join(ROOT, "data", "processed", "existing_content_inventory.json")

HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def _fetch_articles() -> list[dict]:
    """Fetch all articles from the Velluto blog (REST, paginated)."""
    if not (SHOPIFY_TOKEN and SHOPIFY_STORE and BLOG_ID):
        return []
    articles: list[dict] = []
    url = (f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
           "?fields=id,title,handle,tags,body_html,updated_at,published_at,summary_html"
           "&limit=250")
    try:
        while url:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            articles.extend(data.get("articles", []))
            # Shopify Link header pagination
            link = r.headers.get("Link", "")
            next_url = None
            for part in link.split(","):
                if 'rel="next"' in part:
                    next_url = part.split(";")[0].strip(" <>")
            url = next_url
    except Exception as e:
        print(f"      ⚠️  Article fetch error: {e}")
    return articles


def _fetch_collections() -> list[dict]:
    """Fetch active collections (REST). Phase 3 only needs handle + title."""
    if not (SHOPIFY_TOKEN and SHOPIFY_STORE):
        return []
    try:
        r = requests.get(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/smart_collections.json"
            "?fields=id,title,handle,updated_at&limit=50",
            headers=HEADERS, timeout=15,
        )
        r.raise_for_status()
        smart = r.json().get("smart_collections", [])
    except Exception:
        smart = []
    try:
        r = requests.get(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/custom_collections.json"
            "?fields=id,title,handle,updated_at&limit=50",
            headers=HEADERS, timeout=15,
        )
        r.raise_for_status()
        custom = r.json().get("custom_collections", [])
    except Exception:
        custom = []
    return smart + custom


def _primary_keyword(article: dict) -> str:
    """Best-effort: use first tag, else first 5 words of title."""
    tags = article.get("tags", "")
    if tags:
        # Tags is comma-separated; pick the most descriptive one (not 'velluto', 'cycling')
        for t in tags.split(","):
            t = t.strip().lower()
            if t and t not in ("velluto", "cycling", "blog", "magazine", "guide"):
                return t
    return " ".join((article.get("title") or "").lower().split()[:6])


def build() -> dict:
    """
    Build the inventory dict. Returns:
      {
        date: ISO,
        articles: [{id, title, handle, url, primary_keyword, updated_at, word_count, tags}],
        collections: [{id, title, handle, url}],
        total_articles, total_collections,
      }
    """
    today = _dt.date.today().isoformat()
    articles = _fetch_articles()
    collections = _fetch_collections()

    blog_handle = "velluto-the-magazine"

    article_records: list[dict] = []
    for a in articles:
        body = _strip_html(a.get("body_html", ""))
        article_records.append({
            "id":              a.get("id"),
            "title":           a.get("title", ""),
            "handle":          a.get("handle", ""),
            "url":             f"https://velluto-shop.com/blogs/{blog_handle}/{a.get('handle','')}",
            "primary_keyword": _primary_keyword(a),
            "tags":            [t.strip() for t in (a.get("tags") or "").split(",") if t.strip()],
            "updated_at":      a.get("updated_at"),
            "published_at":    a.get("published_at"),
            "word_count":      len(body.split()),
        })

    collection_records = [{
        "id":     c.get("id"),
        "title":  c.get("title", ""),
        "handle": c.get("handle", ""),
        "url":    f"https://velluto-shop.com/collections/{c.get('handle','')}",
        "updated_at": c.get("updated_at"),
    } for c in collections]

    result = {
        "date":              today,
        "articles":          article_records,
        "collections":       collection_records,
        "total_articles":    len(article_records),
        "total_collections": len(collection_records),
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"   ✓ Content inventory: {len(article_records)} articles, {len(collection_records)} collections")
    return result


def find_matching_article(inventory: dict, keyword: str) -> dict | None:
    """Cannibalization helper: return article whose primary_keyword or title overlaps."""
    if not inventory:
        return None
    kw = keyword.lower().strip()
    for a in inventory.get("articles", []):
        if kw == a["primary_keyword"]:
            return a
        # Token-overlap heuristic
        kw_tokens = set(kw.split())
        title_tokens = set(a["title"].lower().split())
        overlap = kw_tokens & title_tokens
        if len(overlap) >= max(2, len(kw_tokens) - 1):
            return a
    return None


if __name__ == "__main__":
    inv = build()
    print(json.dumps({k: v for k, v in inv.items() if k not in ("articles", "collections")},
                     indent=2))
    if inv["articles"]:
        print(f"\nSample article: {inv['articles'][0]['title']}")
        print(f"  primary_keyword: {inv['articles'][0]['primary_keyword']}")
