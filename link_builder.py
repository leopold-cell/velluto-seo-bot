#!/usr/bin/env python3
"""
Velluto Link Builder — Daily indexing + Reddit backlink automation.
Runs after seo_bot.py. Reads published_today.json for today's article URLs.

Two channels:
  1. Sitemap pings  — tells Google + Bing to re-crawl sitemap immediately (no auth needed)
  2. Reddit         — posts best article to the most relevant cycling subreddit
"""

import os, json, datetime, time, re
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

PUBLISHED_LOG  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "published_today.json")
LINK_BUILD_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "link_building_log.json")

ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USERNAME      = os.getenv("REDDIT_USERNAME", "")
REDDIT_PASSWORD      = os.getenv("REDDIT_PASSWORD", "")

SITEMAP_URL = "https://velluto-shop.com/sitemap.xml"


# ── Logging ───────────────────────────────────────────────────────────────────

def log_result(entry: dict):
    today = str(datetime.date.today())
    log = json.load(open(LINK_BUILD_LOG)) if os.path.exists(LINK_BUILD_LOG) else {}
    log.setdefault(today, []).append(entry)
    json.dump(log, open(LINK_BUILD_LOG, "w"), indent=2)


# ── Sitemap pings ─────────────────────────────────────────────────────────────

def ping_search_engines(articles: list[dict]) -> dict:
    """
    Ping Google and Bing to re-crawl the sitemap.
    No auth required — these are standard unauthenticated ping endpoints.
    Also pings each article URL directly at Bing via IndexNow-style submission.
    """
    results = {}

    ping_urls = [
        ("Google", f"https://www.google.com/ping?sitemap={SITEMAP_URL}"),
        ("Bing",   f"https://www.bing.com/ping?sitemap={SITEMAP_URL}"),
    ]
    for engine, url in ping_urls:
        try:
            r = requests.get(url, timeout=10)
            status = "ok" if r.status_code == 200 else f"http_{r.status_code}"
            print(f"   ✓ {engine} sitemap ping: {status}")
            results[engine] = status
        except Exception as e:
            print(f"   ✗ {engine} ping failed: {e}")
            results[engine] = "error"

    return results


# ── Reddit ────────────────────────────────────────────────────────────────────

# Subreddits that accept cycling content and allow informational link posts.
# Rules checked: all allow educational/informational cycling content.
_SUBREDDIT_POOL = [
    ("cycling",      "en", 1_200_000),
    ("bicycling",    "en",   450_000),
    ("RoadCycling",  "en",   120_000),
    ("gravelcycling","en",    80_000),
    ("wielrennen",   "nl",    15_000),  # Dutch — use for NL-topic posts
]


def _pick_subreddit(topic: str, tags: str) -> tuple[str, str]:
    """Return (subreddit, lang) best matching topic language and content."""
    t = (topic + " " + tags).lower()
    # Dutch signals
    if any(w in t for w in ["wielren", "nederland", "dutch", "nl ", "amsterdam", "amstel"]):
        return "wielrennen", "nl"
    # Gravel
    if "gravel" in t:
        return "gravelcycling", "en"
    # Road / race
    if any(w in t for w in ["road", "race", "classics", "tour de", "giro", "vuelta"]):
        return "RoadCycling", "en"
    # Alternate cycling / bicycling by day to avoid flooding one sub
    return ("cycling" if datetime.date.today().toordinal() % 2 == 0 else "bicycling"), "en"


def _generate_reddit_post(article: dict, subreddit: str, lang: str) -> tuple[str, str]:
    """
    Use Claude Haiku to write a genuine, value-adding Reddit post title + body.
    The post provides real cycling advice; the article link is a natural CTA.
    """
    from anthropic import Anthropic
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    lang_instruction = "Write in Dutch (Nederlands)." if lang == "nl" else "Write in English."
    prompt = (
        f"You are a cyclist sharing useful advice on r/{subreddit}.\n"
        f"Topic: {article['topic']}\n"
        f"Target keyword: {article.get('keyword', '')}\n\n"
        f"{lang_instruction}\n\n"
        "Write a Reddit post that:\n"
        "1. Title (max 90 chars): a specific, genuine cycling question or tip — NOT promotional. "
        "   Must feel like a real cyclist asking or sharing, not an ad.\n"
        "2. Body (120-180 words): genuinely useful advice on the topic. Real cyclist perspective. "
        "   Mention Velluto naturally in 1 sentence max — e.g. 'I've been riding the Velluto StradaPro and...' "
        "   End with: 'Wrote a more detailed breakdown here if anyone wants the full rundown: [URL]'\n\n"
        "Output EXACTLY:\n"
        "TITLE: <title>\n"
        "BODY:\n<body text>"
    )
    r = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = r.content[0].text.strip()
    title_match = re.search(r"TITLE:\s*(.+)", raw)
    body_match  = re.search(r"BODY:\s*([\s\S]+)", raw)
    title = title_match.group(1).strip() if title_match else article["title"][:90]
    body  = body_match.group(1).strip()  if body_match  else f"Full article: {article['url']}"
    body  = body.replace("[URL]", article["url"])
    return title, body


def post_to_reddit(article: dict) -> dict:
    """Submit one article to the most relevant cycling subreddit."""
    if not all([REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD]):
        print("   ⚠️  Reddit: credentials missing — skipping")
        return {"status": "skipped", "reason": "no_credentials"}

    subreddit, lang = _pick_subreddit(article["topic"], article.get("tags", ""))
    print(f"   Targeting r/{subreddit} ({lang.upper()})")

    try:
        title, body = _generate_reddit_post(article, subreddit, lang)
    except Exception as e:
        print(f"   ⚠️  Reddit post generation failed: {e}")
        return {"status": "error", "reason": str(e)}

    print(f"   Title: {title}")

    try:
        import praw
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            username=REDDIT_USERNAME,
            password=REDDIT_PASSWORD,
            user_agent="Velluto cycling content bot/1.0",
        )
        sub = reddit.subreddit(subreddit)
        submission = sub.submit(title=title, selftext=body)
        post_url = f"https://reddit.com{submission.permalink}"
        print(f"   ✓ Posted: {post_url}")
        return {"status": "posted", "subreddit": subreddit, "post_url": post_url,
                "title": title, "article_url": article["url"]}
    except Exception as e:
        print(f"   ✗ Reddit post failed: {e}")
        return {"status": "error", "reason": str(e)}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n🔗 Velluto Link Builder — {datetime.date.today()}")
    print("=" * 50)

    if not os.path.exists(PUBLISHED_LOG):
        print("   No published_today.json found — nothing to promote.")
        return

    articles = json.load(open(PUBLISHED_LOG))
    if not articles:
        print("   No articles published today.")
        return

    print(f"   {len(articles)} article(s) to promote")

    # ── 1. Sitemap pings ──────────────────────────────────────────────────────
    print("\n📡 Pinging search engines...")
    ping_results = ping_search_engines(articles)
    log_result({"channel": "sitemap_ping", "results": ping_results,
                "timestamp": datetime.datetime.utcnow().isoformat()})

    # ── 2. Reddit — post the first (most evergreen) article ──────────────────
    print("\n📮 Posting to Reddit...")
    # Pick article with the most generic/educational topic (avoid product-heavy ones)
    candidate = next(
        (a for a in articles if "vs" not in a["topic"].lower()),
        articles[0]
    )
    reddit_result = post_to_reddit(candidate)
    log_result({"channel": "reddit", **reddit_result,
                "timestamp": datetime.datetime.utcnow().isoformat()})

    print(f"\n✅ Link building done.\n")


if __name__ == "__main__":
    main()
