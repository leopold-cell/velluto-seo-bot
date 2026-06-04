#!/usr/bin/env python3
"""
Velluto Pinterest Poster — autonomous daily pinning.

Runs after seo_bot.py / link_builder.py in run.sh. Two pin types:
  1. Article pins  — newest entries from published_today.json, image = og:image
                     of the published article, link = article URL.
  2. Product pins  — rotated across the Shopify catalogue by date, image =
                     Shopify product image, link = product URL.

Descriptions are written by Claude Haiku (Pinterest-optimised, keyword-rich).
Pins are published via the official Pinterest API v5 (image_url media source —
no image hosting/upload needed). Already-posted article URLs / product handles
are remembered in pinterest_log.json and skipped for `dedupe_days`.

Credentials (in .env):
  PINTEREST_ACCESS_TOKEN, PINTEREST_ARTICLE_BOARD_ID, PINTEREST_PRODUCT_BOARD_ID
  (or a single PINTEREST_BOARD_ID used for both), ANTHROPIC_API_KEY, SHOPIFY_*.
Tuning lives in config/pinterest.yml.

If credentials are missing the script logs a warning and exits cleanly, so it is
safe to wire into the daily cron before the token is in place.

Usage:
  python3 pinterest_poster.py            # post per config
  python3 pinterest_poster.py --dry-run  # build pins + descriptions, do NOT post
"""

import os
import re
import sys
import json
import datetime

import requests
import yaml
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(HERE, ".env"), override=True)

# Reuse the proven Shopify helpers from seo_bot (same pattern as
# scripts/fix_internal_links.py). Import is side-effect free (main is guarded).
from seo_bot import get_products  # noqa: E402

PUBLISHED_LOG = os.path.join(HERE, "published_today.json")
PINTEREST_LOG = os.path.join(HERE, "pinterest_log.json")
CONFIG_PATH   = os.path.join(HERE, "config", "pinterest.yml")

ANTHROPIC_API_KEY      = os.getenv("ANTHROPIC_API_KEY", "")
PINTEREST_TOKEN        = os.getenv("PINTEREST_ACCESS_TOKEN", "")
PINTEREST_BOARD_ID     = os.getenv("PINTEREST_BOARD_ID", "")
ARTICLE_BOARD_ID       = os.getenv("PINTEREST_ARTICLE_BOARD_ID", "") or PINTEREST_BOARD_ID
PRODUCT_BOARD_ID       = os.getenv("PINTEREST_PRODUCT_BOARD_ID", "") or PINTEREST_BOARD_ID

# Optional Higfields.ai HTTP image generation (only used if both are set).
HIGHFIELDS_API_KEY     = os.getenv("HIGHFIELDS_API_KEY", "")
HIGHFIELDS_API_URL     = os.getenv("HIGHFIELDS_API_URL", "")

PINS_ENDPOINT   = "https://api.pinterest.com/v5/pins"
BOARDS_ENDPOINT = "https://api.pinterest.com/v5/boards"

DRY_RUN      = "--dry-run" in sys.argv
LIST_BOARDS  = "--list-boards" in sys.argv


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── Logging / dedupe ────────────────────────────────────────────────────────────

def _load_log() -> dict:
    if os.path.exists(PINTEREST_LOG):
        try:
            return json.load(open(PINTEREST_LOG))
        except Exception:
            return {}
    return {}


def log_result(entry: dict):
    log = _load_log()
    today = str(datetime.date.today())
    log.setdefault("runs", {}).setdefault(today, []).append(entry)
    json.dump(log, open(PINTEREST_LOG, "w"), indent=2)


def _recent_keys(dedupe_days: int) -> set[str]:
    """Return the set of pin dedupe keys posted within the dedupe window."""
    log = _load_log()
    cutoff = datetime.date.today() - datetime.timedelta(days=dedupe_days)
    keys: set[str] = set()
    for day, entries in (log.get("runs") or {}).items():
        try:
            d = datetime.date.fromisoformat(day)
        except ValueError:
            continue
        if d < cutoff:
            continue
        for e in entries:
            if e.get("status") == "posted" and e.get("dedupe_key"):
                keys.add(e["dedupe_key"])
    return keys


# ── Images ──────────────────────────────────────────────────────────────────────

def fetch_og_image(url: str) -> str:
    """Scrape the og:image URL from a published page. Returns '' on failure."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return ""
        m = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r.text, re.I,
        ) or re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r.text, re.I,
        )
        if not m:
            return ""
        img = m.group(1).strip()
        # Pinterest prefers https; normalise protocol-relative / http URLs.
        if img.startswith("//"):
            img = "https:" + img
        elif img.startswith("http://"):
            img = "https://" + img[len("http://"):]
        return img
    except Exception:
        return ""


def higfields_generate(prompt: str) -> str:
    """
    OPTIONAL: generate a pin image via the Higfields.ai HTTP API and return a
    public image URL. Disabled unless HIGHFIELDS_API_KEY and HIGHFIELDS_API_URL
    are set (the autonomous VPS cron has no MCP access, so a direct HTTP endpoint
    is required). Returns '' on any failure so the caller falls back to og/Shopify
    images and the run never breaks.
    """
    if not (HIGHFIELDS_API_KEY and HIGHFIELDS_API_URL):
        return ""
    try:
        r = requests.post(
            HIGHFIELDS_API_URL,
            headers={"Authorization": f"Bearer {HIGHFIELDS_API_KEY}",
                     "Content-Type": "application/json"},
            json={"prompt": prompt},
            timeout=60,
        )
        if r.status_code not in (200, 201):
            print(f"   ⚠️  Higfields: http_{r.status_code} — falling back")
            return ""
        data = r.json()
        # Accept a few common response shapes.
        return (data.get("image_url") or data.get("url")
                or (data.get("data") or [{}])[0].get("url", ""))
    except Exception as e:
        print(f"   ⚠️  Higfields generation failed: {e} — falling back")
        return ""


def resolve_article_image(article: dict, sources: list[str]) -> str:
    for src in sources:
        if src == "og_image":
            img = fetch_og_image(article["url"])
            if img:
                return img
        elif src == "higfields":
            img = higfields_generate(
                f"Editorial Pinterest pin, premium road cycling eyewear, "
                f"topic: {article.get('topic', article['title'])}, Velluto brand, "
                f"clean minimal Italian design, 2:3 vertical"
            )
            if img:
                return img
    return ""


def _sized(image_url: str, width: int = 1000) -> str:
    """Request a Pinterest-friendly width from Shopify CDN images."""
    if "cdn/shop" not in image_url and "cdn.shopify" not in image_url:
        return image_url
    sep = "&" if "?" in image_url else "?"
    return f"{image_url}{sep}width={width}"


# ── Description copywriting (Claude Haiku) ───────────────────────────────────────

def _hashtag_str(cfg: dict) -> str:
    tags = cfg.get("hashtags") or []
    return " ".join(tags)


def generate_description(kind: str, item: dict, cfg: dict) -> tuple[str, str]:
    """
    Return (title, description) for a pin. Falls back to safe defaults if the
    LLM call fails. Pinterest limits: title <=100 chars, description <=800.
    """
    title = (item.get("title") or "Velluto cycling eyewear")[:100]
    hashtags = _hashtag_str(cfg)
    fallback_desc = (
        f"{title} — premium lightweight cycling eyewear by Velluto. "
        f"{hashtags}"
    )[:800]

    if not ANTHROPIC_API_KEY:
        return title, fallback_desc

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        if kind == "article":
            ctx = (f"Blog article titled '{item['title']}'. "
                   f"Topic: {item.get('topic', '')}. "
                   f"Target keyword: {item.get('keyword', '')}.")
        else:
            ctx = (f"Product '{item['title']}' from Velluto, a premium road "
                   f"cycling eyewear brand (Italian design, lightweight, "
                   f"interchangeable lenses, UV400).")
        prompt = (
            "Write a Pinterest pin for Velluto (premium road cycling eyewear).\n"
            f"{ctx}\n\n"
            "Output EXACTLY:\n"
            "TITLE: <max 95 chars, specific and clickable, no emojis>\n"
            "DESC: <2-3 sentences, keyword-rich, value-led, ends with a soft CTA; "
            "max 480 chars; do NOT include hashtags or URLs>"
        )
        r = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = r.content[0].text.strip()
        t = re.search(r"TITLE:\s*(.+)", raw)
        d = re.search(r"DESC:\s*([\s\S]+)", raw)
        if t:
            title = t.group(1).strip()[:100]
        desc = (d.group(1).strip() if d else fallback_desc)
        desc = f"{desc} {hashtags}".strip()[:800]
        return title, desc
    except Exception as e:
        print(f"   ⚠️  description generation failed: {e} — using fallback")
        return title, fallback_desc


# ── Pinterest API ────────────────────────────────────────────────────────────────

def create_pin(board_id: str, title: str, description: str, link: str,
               image_url: str) -> dict:
    payload = {
        "board_id": board_id,
        "title": title[:100],
        "description": description[:800],
        "link": link,
        "media_source": {"source_type": "image_url", "url": image_url},
    }
    if DRY_RUN:
        print(f"   [dry-run] would post → board {board_id}")
        print(f"            title: {title}")
        print(f"            image: {image_url}")
        print(f"            link:  {link}")
        return {"status": "dry_run"}
    try:
        r = requests.post(
            PINS_ENDPOINT,
            headers={"Authorization": f"Bearer {PINTEREST_TOKEN}",
                     "Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        if r.status_code in (200, 201):
            pin_id = r.json().get("id", "")
            print(f"   ✓ Pinned: {pin_id} — {title}")
            return {"status": "posted", "pin_id": pin_id}
        print(f"   ✗ Pinterest error {r.status_code}: {r.text[:200]}")
        return {"status": "error", "reason": f"http_{r.status_code}", "detail": r.text[:200]}
    except Exception as e:
        print(f"   ✗ Pinterest post failed: {e}")
        return {"status": "error", "reason": str(e)}


# ── Boards ───────────────────────────────────────────────────────────────────────

def get_boards() -> list[dict]:
    """Return the account's boards [{id, name}, ...] via Pinterest API v5."""
    boards, bookmark = [], None
    try:
        while True:
            params = {"page_size": 100}
            if bookmark:
                params["bookmark"] = bookmark
            r = requests.get(
                BOARDS_ENDPOINT,
                headers={"Authorization": f"Bearer {PINTEREST_TOKEN}"},
                params=params, timeout=30,
            )
            if r.status_code != 200:
                print(f"   ⚠️  could not list boards: http_{r.status_code} {r.text[:120]}")
                break
            data = r.json()
            boards.extend(data.get("items", []))
            bookmark = data.get("bookmark")
            if not bookmark:
                break
    except Exception as e:
        print(f"   ⚠️  board listing failed: {e}")
    return boards


def resolve_board_id_by_name(name: str, boards: list[dict] | None = None) -> str:
    """Match a board by name (case-insensitive). Returns '' if not found."""
    if not name:
        return ""
    boards = boards if boards is not None else get_boards()
    target = name.strip().lower()
    for b in boards:
        if (b.get("name") or "").strip().lower() == target:
            return b.get("id", "")
    return ""


# ── Pin builders ─────────────────────────────────────────────────────────────────

def post_article_pins(cfg: dict, recent: set[str], board_id: str) -> int:
    limit = (cfg.get("limits") or {}).get("article_pins_per_day", 2)
    sources = cfg.get("article_image_sources") or ["og_image"]
    if not board_id and not DRY_RUN:
        print("   ⚠️  no article board id — skipping article pins")
        return 0
    if not os.path.exists(PUBLISHED_LOG):
        print("   ⚠️  no published_today.json — no article pins")
        return 0
    try:
        articles = json.load(open(PUBLISHED_LOG)) or []
    except Exception:
        articles = []

    posted = 0
    for article in articles:
        if posted >= limit:
            break
        key = f"article:{article.get('url','')}"
        if not article.get("url") or key in recent:
            continue
        print(f"\n📌 Article pin: {article['title'][:60]}")
        image = resolve_article_image(article, sources)
        if not image:
            print("   ⚠️  no image found — skipping")
            continue
        title, desc = generate_description("article", article, cfg)
        res = create_pin(board_id, title, desc, article["url"], image)
        res.update({"kind": "article", "dedupe_key": key, "link": article["url"]})
        log_result(res)
        if res.get("status") in ("posted", "dry_run"):
            posted += 1
            recent.add(key)
    return posted


def post_product_pins(cfg: dict, recent: set[str], board_id: str) -> int:
    limit = (cfg.get("limits") or {}).get("product_pins_per_day", 1)
    if not board_id and not DRY_RUN:
        print("   ⚠️  no product board id — skipping product pins")
        return 0
    try:
        products = [p for p in get_products() if p.get("image")]
    except Exception as e:
        print(f"   ⚠️  could not load products: {e}")
        return 0
    if not products:
        print("   ⚠️  no products with images — no product pins")
        return 0

    # Deterministic daily rotation so we cycle the catalogue evenly.
    start = datetime.date.today().toordinal() % len(products)
    ordered = products[start:] + products[:start]

    posted = 0
    for product in ordered:
        if posted >= limit:
            break
        key = f"product:{product['handle']}"
        if key in recent:
            continue
        print(f"\n📌 Product pin: {product['title'][:60]}")
        title, desc = generate_description("product", product, cfg)
        res = create_pin(board_id, title, desc, product["url"],
                         _sized(product["image"]))
        res.update({"kind": "product", "dedupe_key": key, "link": product["url"]})
        log_result(res)
        if res.get("status") in ("posted", "dry_run"):
            posted += 1
            recent.add(key)
    return posted


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n📌 Velluto Pinterest Poster — {datetime.date.today()}"
          f"{' [DRY-RUN]' if DRY_RUN else ''}")
    print("=" * 50)

    cfg = load_config()

    if LIST_BOARDS:
        if not PINTEREST_TOKEN:
            print("   ⚠️  PINTEREST_ACCESS_TOKEN missing — set it in .env first")
            return
        boards = get_boards()
        print(f"   {len(boards)} board(s):")
        for b in boards:
            print(f"     {b.get('id','?'):<20} {b.get('name','')}")
        return

    if not cfg.get("enabled", True):
        print("   Pinterest posting disabled in config/pinterest.yml — exiting")
        return

    if not DRY_RUN and not PINTEREST_TOKEN:
        print("   ⚠️  PINTEREST_ACCESS_TOKEN missing — skipping (set it in .env)")
        return

    # Resolve effective board ids: explicit numeric env ids win; otherwise resolve
    # the configured board name(s) via the API so no numeric id hunting is needed.
    article_board = ARTICLE_BOARD_ID
    product_board = PRODUCT_BOARD_ID
    boards_cache: list[dict] | None = None
    if PINTEREST_TOKEN and not (article_board and product_board):
        names = cfg.get("boards") or {}
        default_name = names.get("name", "")
        article_name = names.get("article", "") or default_name
        product_name = names.get("product", "") or default_name
        if (article_name and not article_board) or (product_name and not product_board):
            boards_cache = get_boards()
            if not article_board and article_name:
                article_board = resolve_board_id_by_name(article_name, boards_cache)
                print(f"   Resolved article board '{article_name}' → {article_board or 'NOT FOUND'}")
            if not product_board and product_name:
                product_board = resolve_board_id_by_name(product_name, boards_cache)
                print(f"   Resolved product board '{product_name}' → {product_board or 'NOT FOUND'}")

    if not DRY_RUN and not (article_board or product_board):
        print("   ⚠️  No board resolved — set PINTEREST_BOARD_ID or a board name in "
              "config/pinterest.yml (boards.name) — skipping")
        return

    recent = _recent_keys(cfg.get("dedupe_days", 90))

    n_articles = post_article_pins(cfg, recent, article_board)
    n_products = post_product_pins(cfg, recent, product_board)

    print("\n" + "=" * 50)
    print(f"   Done — {n_articles} article pin(s), {n_products} product pin(s)")


if __name__ == "__main__":
    main()
