#!/usr/bin/env python3
"""
Velluto SEO Optimizer — runs daily after blog posts are published.

1. Checks what top-ranking competitors are doing for our target keywords
2. Reviews our recent posts for gaps vs competitors
3. Uses Claude to derive specific improvement actions
4. Saves insights to seo_insights.json — injected into next day's generation
"""

import os, json, datetime, re, requests, time
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

client       = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID       = os.getenv("BLOG_ID", "127785959765")
SHOPIFY_HDR   = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

BASE         = os.path.dirname(os.path.abspath(__file__))
INSIGHTS_LOG = os.path.join(BASE, "seo_insights.json")
USAGE_LOG    = os.path.join(BASE, "token_usage.json")

# Keywords to analyse competitors for (pick highest-value subset to stay within DDG limits)
ANALYSIS_KEYWORDS = [
    "best cycling glasses 2026",
    "wielrenbril kopen",
    "interchangeable lens cycling glasses",
    "anti-fog cycling glasses",
    "road cycling glasses review",
]

COMPETITORS = {
    "POC":          "pocbike.com",
    "Blitz":        "blitzeyewear.com",
    "Oakley":       "oakley.com",
    "Rapha":        "rapha.cc",
    "Rudy Project": "rudyproject.com",
    "Evil Eye":     "evil-eye.com",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def log_usage(inp: int, out: int):
    today = str(datetime.date.today())
    log = json.load(open(USAGE_LOG)) if os.path.exists(USAGE_LOG) else {}
    e = log.setdefault(today, {"runs": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    e["runs"] += 1; e["input_tokens"] += inp; e["output_tokens"] += out
    cost = (inp * 3.0 + out * 15.0) / 1_000_000
    e["cost_usd"] = round(e["cost_usd"] + cost, 6)
    json.dump(log, open(USAGE_LOG, "w"), indent=2)
    return cost


def clean_html(html: str) -> str:
    return re.sub(r'<[^>]+>', ' ', html).strip()


def fetch_page_intel(url: str) -> dict | None:
    """Fetch a competitor page and extract SEO signals."""
    try:
        r = requests.get(url, timeout=8,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; SEO-research/1.0)"})
        if r.status_code != 200:
            return None
        html = r.text
        title    = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
        meta_d   = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, re.I)
        h1s      = re.findall(r'<h1[^>]*>(.*?)</h1>', html, re.I | re.S)
        h2s      = re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.I | re.S)
        body_txt = clean_html(html)
        word_count = len(body_txt.split())
        has_faq  = bool(re.search(r'faq|frequently asked|veelgesteld', html, re.I))
        has_table = bool(re.search(r'<table', html, re.I))
        has_review = bool(re.search(r'review|beoordeling|recensie|testimonial', html, re.I))
        return {
            "url": url,
            "title": clean_html(title.group(1)) if title else "",
            "meta_description": clean_html(meta_d.group(1)) if meta_d else "",
            "h1": [clean_html(h) for h in h1s[:2]],
            "h2s": [clean_html(h) for h in h2s[:6]],
            "word_count": word_count,
            "has_faq": has_faq,
            "has_table": has_table,
            "has_reviews": has_review,
        }
    except Exception as e:
        return None


# ── Competitor research ───────────────────────────────────────────────────────

def research_competitors() -> dict:
    """
    For each analysis keyword: get top search results, identify competitor pages,
    fetch their SEO structure.
    """
    findings = {}
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            for kw in ANALYSIS_KEYWORDS:
                print(f"   Researching: '{kw}'...")
                try:
                    hits = list(ddgs.text(kw, max_results=10))
                except Exception:
                    hits = []
                top_pages = []
                for hit in hits:
                    url  = hit.get("href", "")
                    body = hit.get("body", "")
                    titl = hit.get("title", "")
                    if "velluto" in url.lower():
                        continue
                    # Include any cycling/eyewear relevant result, not just known competitors
                    intel = {
                        "url": url,
                        "title": titl,
                        "snippet": body[:200],
                        "competitor": next((n for n, d in COMPETITORS.items() if d in url.lower()), "other"),
                    }
                    # Try to fetch page structure for top 3 results
                    if len(top_pages) < 3:
                        page = fetch_page_intel(url)
                        if page:
                            intel.update(page)
                    top_pages.append(intel)
                    if len(top_pages) >= 5:
                        break
                findings[kw] = top_pages
                time.sleep(2)
    except Exception as e:
        print(f"   ✗ Competitor research failed: {e}")
    return findings


# ── Our recent posts ──────────────────────────────────────────────────────────

def get_recent_posts(n=6) -> list[dict]:
    r = requests.get(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        f"?limit={n}&fields=id,title,body_html,tags,created_at",
        headers=SHOPIFY_HDR, timeout=15)
    posts = r.json().get("articles", [])
    result = []
    for p in posts:
        body  = clean_html(p.get("body_html", ""))
        h2s   = re.findall(r'<h2[^>]*>(.*?)</h2>', p.get("body_html",""), re.I|re.S)
        result.append({
            "title":      p["title"],
            "date":       p["created_at"][:10],
            "word_count": len(body.split()),
            "h2s":        [clean_html(h) for h in h2s[:5]],
            "tags":       p.get("tags",""),
            "has_faq":    "faq" in body.lower() or "frequently" in body.lower(),
            "has_table":  "<table" in p.get("body_html","").lower(),
        })
    return result


# ── Claude analysis ───────────────────────────────────────────────────────────

def analyse_and_generate_insights(competitor_data: dict, our_posts: list[dict]) -> dict:
    """Claude analyses competitor patterns vs our posts and generates actionable insights."""

    comp_summary = json.dumps(competitor_data, indent=2)[:6000]
    our_summary  = json.dumps(our_posts, indent=2)[:2000]

    today = str(datetime.date.today())

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system="""You are an expert SEO strategist analysing a cycling eyewear brand (Velluto, velluto-shop.com).
Your job: analyse competitor search rankings and content, compare to Velluto's recent posts,
and produce specific, actionable improvements for tomorrow's blog posts.
Be concrete — cite patterns you actually see in the data, not generic advice.""",
        messages=[{"role": "user", "content": f"""
Today: {today}

TOP COMPETITOR CONTENT (search results + page structure):
{comp_summary}

OUR RECENT POSTS:
{our_summary}

Analyse and return ONLY this JSON (no extra text):
{{
  "analysis_date": "{today}",
  "competitor_patterns": [
    "3-5 specific patterns you see in top-ranking competitor content (structure, word count, topics, features)"
  ],
  "our_gaps": [
    "3-5 specific gaps where our posts fall short vs competitors"
  ],
  "keyword_opportunities": [
    "3-5 specific long-tail keywords competitors rank for that we haven't covered"
  ],
  "next_post_guidelines": [
    "5-7 specific writing instructions for tomorrow's posts (e.g. word count target, must-include sections, tone, specific keywords to use)"
  ],
  "seo_quick_wins": [
    "2-3 immediate technical/structural improvements to apply to all future posts"
  ],
  "geo_angles": [
    "2-3 angles that would help Velluto appear in AI-generated answers (ChatGPT, Perplexity, Google AI Overview)"
  ]
}}
"""}]
    )
    cost = log_usage(response.usage.input_tokens, response.usage.output_tokens)
    print(f"   Claude analysis: {response.usage.input_tokens} in / {response.usage.output_tokens} out | ${cost:.4f}")

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n🔍 Velluto SEO Optimizer — {datetime.date.today()}")
    print("=" * 55)

    print("📡 Researching competitor content...")
    competitor_data = research_competitors()

    print("📋 Fetching our recent posts...")
    our_posts = get_recent_posts(6)
    print(f"   {len(our_posts)} recent posts analysed")

    print("🧠 Running Claude SEO analysis...")
    try:
        insights = analyse_and_generate_insights(competitor_data, our_posts)
        json.dump(insights, open(INSIGHTS_LOG, "w"), indent=2)
        print(f"   ✓ Insights saved to seo_insights.json")
        print(f"   Gaps found: {len(insights.get('our_gaps', []))}")
        print(f"   Opportunities: {len(insights.get('keyword_opportunities', []))}")
    except Exception as e:
        print(f"   ✗ Analysis failed: {e}")
        # Don't crash the whole workflow — seo_bot.py runs fine without insights


if __name__ == "__main__":
    main()
