#!/usr/bin/env python3
"""
Velluto SEO Optimizer — runs daily after blog posts are published.

1. Checks what top-ranking competitors are doing for our target keywords
2. Reviews our recent posts for gaps vs competitors
3. Uses Claude to derive specific improvement actions
4. Saves insights to seo_insights.json — injected into next day's generation
"""

import os, json, datetime, re, requests, time, urllib.parse
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

client        = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID       = os.getenv("BLOG_ID", "127785959765")
SHOPIFY_HDR   = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

BASE            = os.path.dirname(os.path.abspath(__file__))
INSIGHTS_LOG    = os.path.join(BASE, "seo_insights.json")
USAGE_LOG       = os.path.join(BASE, "token_usage.json")
DYNAMIC_LOG     = os.path.join(BASE, "topics_dynamic.json")
TOPIC_LOG       = os.path.join(BASE, "topics_used.json")
COMPETITORS_LOG = os.path.join(BASE, "competitors_discovered.json")
GSC_LOG         = os.path.join(BASE, "gsc_data.json")

GSC_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GSC_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GSC_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN", "")
GSC_SITE_URL      = "https://velluto-shop.com/"

# Multilingual keyword sets — one per shop language (EN / NL / DE)
ANALYSIS_KEYWORDS = {
    "en": [
        "best cycling glasses 2026",
        "road cycling glasses review",
        "interchangeable lens cycling glasses",
        "anti-fog cycling glasses",
        "buy cycling sunglasses",
        "lightweight road cycling glasses",
    ],
    "nl": [
        "wielrenbril kopen",
        "beste wielrenbril 2026",
        "wielrenbril met verwisselbare glazen",
        "sportbril wielrennen test",
        "fietsbril kopen",
    ],
    "de": [
        "Rennradbrille kaufen 2026",
        "beste Fahrradbrille Test",
        "Rennradbrille Wechselgläser",
        "Fahrradbrille UV400 kaufen",
        "leichte Rennradbrille",
    ],
}

# Domains that are NOT brand competitors (retailers, media, marketplaces, aggregators)
_SKIP_DOMAINS = {
    "amazon", "bol.com", "google", "youtube", "reddit", "trustpilot", "kiyoh",
    "wikipedia", "instagram", "facebook", "twitter", "pinterest", "tiktok",
    "decathlon", "wiggle", "chainreactioncycles", "bike24", "bikester",
    "coolblue", "mediamarkt", "sportsdirect", "aliexpress", "ebay",
    "cyclingnews", "bikeradar", "velonews", "cyclingweekly", "rouleur",
    "fiets.nl", "wielrennen.nl", "strava", "komoot", "garmin",
    "velluto",  # ourselves
}


def extract_brand_name(domain: str) -> str:
    """Turn a domain into a clean brand name. e.g. 'uvex-sports.com' → 'Uvex'."""
    name = re.sub(r'\.(com|nl|de|cc|co\.uk|eu|be|fr|es|it|us)$', '', domain, flags=re.I)
    for suffix in ["-sports", "-eyewear", "-optics", "-glasses", "-cycling",
                   "sports", "eyewear", "optics", "glasses", "cycling", "bike"]:
        name = re.sub(rf'{re.escape(suffix)}$', '', name, flags=re.I)
    name = name.replace("-", " ").strip()
    words = []
    for w in name.split():
        words.append(w.upper() if len(w) <= 3 else w.capitalize())
    return " ".join(words) or domain

# Velluto's honest advantages to use in comparison posts
VELLUTO_ADVANTAGES = """
Velluto StradaPro advantages over premium competitors:
- 25g ultralight frame (lighter than most premium brands)
- Interchangeable lenses (VellutoPuro clear + VellutoVisione high-contrast) — click-in, tool-free
- 30-day risk-free trial — test on real rides before committing
- Anti-fog system built-in
- UV400 certified
- Italian design aesthetic at a fraction of premium brand pricing
- Adjustable nose pads for custom fit
- Free shipping over €99
"""


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


# ── Google Search Console ────────────────────────────────────────────────────

def _gsc_token() -> str | None:
    if not all([GSC_CLIENT_ID, GSC_CLIENT_SECRET, GSC_REFRESH_TOKEN]):
        return None
    try:
        r = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": GSC_CLIENT_ID, "client_secret": GSC_CLIENT_SECRET,
            "refresh_token": GSC_REFRESH_TOKEN, "grant_type": "refresh_token",
        }, timeout=15)
        return r.json().get("access_token")
    except Exception as e:
        print(f"   ⚠️  GSC token error: {e}")
        return None


def fetch_gsc() -> dict:
    """Fetch 28-day GSC search analytics. Saves to gsc_data.json for dashboard to reuse."""
    today = str(datetime.date.today())
    if os.path.exists(GSC_LOG):
        cached = json.load(open(GSC_LOG))
        if cached.get("date") == today:
            print("   GSC: using today's cache.")
            return cached

    token = _gsc_token()
    if not token:
        print("   ⚠️  GSC: credentials missing — skipping.")
        return {}

    end_date   = today
    start_date = str(datetime.date.today() - datetime.timedelta(days=28))
    site       = urllib.parse.quote(GSC_SITE_URL, safe="")
    hdrs       = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _q(dimensions, row_limit=25):
        try:
            r = requests.post(
                f"https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query",
                headers=hdrs,
                json={"startDate": start_date, "endDate": end_date,
                      "dimensions": dimensions, "rowLimit": row_limit},
                timeout=15,
            )
            return r.json().get("rows", [])
        except Exception as e:
            print(f"   ⚠️  GSC query error: {e}")
            return []

    data = {
        "date":        today,
        "top_queries": _q(["query"], row_limit=25),
        "top_pages":   _q(["page"],  row_limit=10),
        "daily_trend": _q(["date"],  row_limit=28),
    }
    json.dump(data, open(GSC_LOG, "w"), indent=2)
    total_clicks = sum(r.get("clicks", 0) for r in data["top_queries"])
    print(f"   ✓ GSC: {len(data['top_queries'])} queries, {int(total_clicks)} clicks (28d)")
    return data


def gsc_opportunities(gsc: dict) -> dict:
    """
    Extract three actionable opportunity sets from GSC data:
    - low_ctr:   high impressions but <3% CTR → meta title/description fix needed
    - near_top:  positions 4-20 with good impressions → content depth push to top 3
    - top_performing: already winning queries → double down on these topics
    """
    queries = gsc.get("top_queries", [])
    if not queries:
        return {}

    low_ctr, near_top, top_performing = [], [], []

    for row in queries:
        kw   = row["keys"][0]
        impr = row.get("impressions", 0)
        ctr  = row.get("ctr", 0)
        pos  = row.get("position", 99)
        clks = row.get("clicks", 0)

        if impr >= 30 and ctr < 0.03 and pos <= 25:
            low_ctr.append({
                "query": kw, "impressions": int(impr),
                "ctr_pct": round(ctr * 100, 1), "avg_position": round(pos, 1),
            })

        if 4 <= pos <= 20 and impr >= 15:
            near_top.append({
                "query": kw, "avg_position": round(pos, 1),
                "impressions": int(impr), "clicks": int(clks),
            })

        if clks >= 3:
            top_performing.append({"query": kw, "clicks": int(clks), "ctr_pct": round(ctr * 100, 1)})

    return {
        "low_ctr_keywords": sorted(low_ctr, key=lambda x: x["impressions"], reverse=True)[:6],
        "near_top_keywords": sorted(near_top, key=lambda x: x["impressions"], reverse=True)[:8],
        "top_performing": sorted(top_performing, key=lambda x: x["clicks"], reverse=True)[:5],
    }


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

def is_competitor(domain: str) -> bool:
    """True if domain looks like a brand competitor, not a retailer/media/marketplace."""
    d = domain.lower()
    return not any(skip in d for skip in _SKIP_DOMAINS)


def load_known_competitors() -> dict:
    """Load previously discovered competitors {domain: brand_name}."""
    return json.load(open(COMPETITORS_LOG)) if os.path.exists(COMPETITORS_LOG) else {}


def save_known_competitors(registry: dict):
    json.dump(registry, open(COMPETITORS_LOG, "w"), indent=2)


def research_competitors() -> dict:
    """
    Search all languages (EN/NL/DE), discover any brand ranking in top 5 dynamically.
    Returns {keyword: [page_intel, ...]} across all languages.
    """
    findings   = {}
    registry   = load_known_competitors()  # persist discovered brands across runs
    new_brands = 0

    try:
        from ddgs import DDGS
        all_keywords = [
            (lang, kw)
            for lang, kws in ANALYSIS_KEYWORDS.items()
            for kw in kws
        ]
        with DDGS() as ddgs:
            for lang, kw in all_keywords:
                print(f"   [{lang.upper()}] '{kw}'")
                try:
                    hits = list(ddgs.text(kw, max_results=10))
                except Exception:
                    hits = []

                top_pages = []
                for hit in hits:
                    url  = hit.get("href", "")
                    body = hit.get("body", "")
                    titl = hit.get("title", "")

                    # Extract domain
                    m = re.search(r'https?://(?:www\.)?([^/]+)', url)
                    if not m:
                        continue
                    domain = m.group(1).lower()

                    if not is_competitor(domain):
                        continue

                    # Register new competitor dynamically
                    if domain not in registry:
                        brand = extract_brand_name(domain)
                        registry[domain] = brand
                        new_brands += 1
                        print(f"      🆕 Discovered competitor: {brand} ({domain})")
                    else:
                        brand = registry[domain]

                    intel = {
                        "url":        url,
                        "title":      titl,
                        "snippet":    body[:200],
                        "competitor": brand,
                        "domain":     domain,
                        "language":   lang,
                    }
                    # Deep-fetch page structure for top 3 per keyword
                    if len(top_pages) < 3:
                        page = fetch_page_intel(url)
                        if page:
                            intel.update(page)

                    top_pages.append(intel)
                    if len(top_pages) >= 5:
                        break

                if top_pages:
                    findings[f"[{lang.upper()}] {kw}"] = top_pages
                time.sleep(1.5)

    except Exception as e:
        print(f"   ✗ Competitor research failed: {e}")

    save_known_competitors(registry)
    if new_brands:
        print(f"   ✓ {new_brands} new competitor(s) added to registry ({len(registry)} total)")
    return findings


# ── Competitor ranking detection ─────────────────────────────────────────────

def detect_top_competitors(competitor_data: dict) -> list[dict]:
    """
    Find any brand ranking in top 3 across all language keyword searches.
    Returns list sorted by position (best first).
    """
    hits = []
    for kw, pages in competitor_data.items():
        for i, page in enumerate(pages[:3], start=1):
            name = page.get("competitor", "")
            if name:
                hits.append({
                    "competitor": name,
                    "domain":     page.get("domain", ""),
                    "keyword":    kw,
                    "position":   i,
                    "title":      page.get("title", ""),
                    "snippet":    page.get("snippet", ""),
                    "h2s":        page.get("h2s", []),
                    "word_count": page.get("word_count", 0),
                    "language":   page.get("language", "en"),
                })
    hits.sort(key=lambda x: x["position"])
    return hits


def generate_comparison_topics(top_competitors: list[dict], already_used: list[str]) -> list[str]:
    """
    For each top-ranking competitor (any brand, any language), generate a
    targeted comparison topic in the language of the keyword that triggered it.
    """
    if not top_competitors:
        return []

    seen = set()
    unique = []
    for h in top_competitors:
        if h["competitor"] not in seen:
            seen.add(h["competitor"])
            unique.append(h)

    topics = []
    for h in unique[:5]:
        name = h["competitor"]
        kw   = h["keyword"]        # e.g. "[NL] wielrenbril kopen"
        pos  = h["position"]
        lang = h.get("language", "en")

        already_covered = any(
            name.lower() in t.lower() and "vs" in t.lower()
            for t in already_used
        )
        if already_covered:
            print(f"   {name} comparison already published — skipping")
            continue

        # Match topic language to keyword language
        if lang == "nl" or "wielrenbril" in kw or "fietsbril" in kw:
            if "kopen" in kw or "beste" in kw:
                topic = f"{name} wielrenbril vs Velluto StradaPro — welke is het waard in 2026"
            elif "test" in kw or "review" in kw:
                topic = f"{name} vs Velluto — eerlijke vergelijking voor wielrenners"
            else:
                topic = f"{name} vs Velluto StradaPro wielrenbril — eerlijke vergelijking 2026"
        elif lang == "de" or "Rennrad" in kw or "Fahrrad" in kw:
            if "kaufen" in kw or "beste" in kw:
                topic = f"{name} vs Velluto StradaPro Rennradbrille — welche lohnt sich 2026"
            else:
                topic = f"{name} Rennradbrille vs Velluto — ehrlicher Vergleich 2026"
        else:
            if "buy" in kw or "best" in kw:
                topic = f"{name} vs Velluto StradaPro — which cycling glasses are worth buying in 2026"
            elif "review" in kw:
                topic = f"{name} cycling glasses vs Velluto — an honest comparison"
            else:
                topic = f"{name} vs Velluto cycling glasses — same performance, better value"

        print(f"   → Queued: '{topic}' [{lang.upper()}] (#{pos} for '{kw}')")
        topics.append(topic)

    return topics


def inject_priority_topics(topics: list[str]):
    """Prepend comparison topics to the dynamic pool so they get picked next."""
    if not topics:
        return
    existing = json.load(open(DYNAMIC_LOG)) if os.path.exists(DYNAMIC_LOG) else []
    # Put comparison topics at the FRONT — they have high buyer intent
    merged = list(dict.fromkeys(topics + existing))
    json.dump(merged, open(DYNAMIC_LOG, "w"), indent=2)
    print(f"   ✓ {len(topics)} comparison topic(s) added to priority queue")


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

def analyse_and_generate_insights(competitor_data: dict, our_posts: list[dict],
                                   top_competitors: list[dict],
                                   gsc_opps: dict) -> dict:
    """Claude analyses competitor patterns + real GSC data and generates actionable insights."""

    comp_summary  = json.dumps(competitor_data, indent=2)[:5000]
    our_summary   = json.dumps(our_posts, indent=2)[:2000]
    top_comp_str  = json.dumps(top_competitors[:6], indent=2)[:1500]
    gsc_str       = json.dumps(gsc_opps, indent=2)[:2000] if gsc_opps else "No GSC data available yet."
    today = str(datetime.date.today())

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system=f"""You are an expert SEO strategist analysing a cycling eyewear brand (Velluto, velluto-shop.com).
Your job: use real Google Search Console data + competitor analysis to produce specific, data-driven
improvements. Prioritise actions based on actual search impressions and click data.

{VELLUTO_ADVANTAGES}""",
        messages=[{"role": "user", "content": f"""
Today: {today}

GOOGLE SEARCH CONSOLE DATA (real Google impressions + clicks, last 28 days):
{gsc_str}

TOP COMPETITOR CONTENT (search results + page structure):
{comp_summary}

COMPETITORS RANKING IN TOP 3:
{top_comp_str}

OUR RECENT POSTS:
{our_summary}

Use the GSC data to prioritise: low-CTR keywords need meta title fixes, near-top keywords
need deeper content. Analyse and return ONLY this JSON (no extra text):
{{
  "analysis_date": "{today}",
  "competitor_patterns": [
    "3-5 specific patterns you see in top-ranking competitor content"
  ],
  "our_gaps": [
    "3-5 specific gaps where our posts fall short vs top-ranking competitors"
  ],
  "keyword_opportunities": [
    "3-5 specific long-tail keywords competitors rank for that we haven't covered"
  ],
  "next_post_guidelines": [
    "5-7 specific writing instructions for tomorrow's posts based on GSC + competitor data"
  ],
  "seo_quick_wins": [
    "2-3 immediate structural improvements to apply to all future posts"
  ],
  "meta_title_fixes": [
    "For each low-CTR keyword from GSC: suggest a new meta title (max 60 chars) that will improve CTR. Format: 'QUERY → New title: [title] | Why: [reason]'"
  ],
  "content_quick_wins": [
    "For each near-top-3 keyword from GSC: suggest a specific blog post topic or content angle to push it from position X to top 3. Format: 'QUERY (pos X) → Topic: [topic] | Add: [what content to add]'"
  ],
  "geo_angles": [
    "2-3 angles that help Velluto appear in AI answers (ChatGPT, Perplexity, Google AI Overview)"
  ],
  "comparison_post_angles": [
    "For each top-ranking competitor: 1 specific angle for a Velluto vs [Competitor] post. Format: 'COMPETITOR: angle — headline idea, key differentiator, Velluto advantage to lead with'"
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

    print("📊 Fetching Google Search Console data...")
    gsc      = fetch_gsc()
    gsc_opps = gsc_opportunities(gsc)
    if gsc_opps.get("low_ctr_keywords"):
        print(f"   Low-CTR keywords: {len(gsc_opps['low_ctr_keywords'])} (meta fix needed)")
    if gsc_opps.get("near_top_keywords"):
        print(f"   Near-top-3 keywords: {len(gsc_opps['near_top_keywords'])} (content push needed)")

    print("📡 Researching competitor content...")
    competitor_data = research_competitors()

    print("🎯 Detecting top-ranking competitors...")
    top_competitors = detect_top_competitors(competitor_data)
    if top_competitors:
        for h in top_competitors[:5]:
            print(f"   {h['competitor']} ranks #{h['position']} for '{h['keyword']}'")
    else:
        print("   No known competitors found in top 3")

    print("📋 Fetching our recent posts...")
    our_posts    = get_recent_posts(6)
    already_used = json.load(open(TOPIC_LOG)) if os.path.exists(TOPIC_LOG) else []
    print(f"   {len(our_posts)} recent posts analysed")

    print("🥊 Generating comparison post topics...")
    comparison_topics = generate_comparison_topics(top_competitors, already_used)
    if comparison_topics:
        inject_priority_topics(comparison_topics)

    print("🧠 Running Claude SEO analysis (with GSC data)...")
    try:
        insights = analyse_and_generate_insights(
            competitor_data, our_posts, top_competitors, gsc_opps)
        json.dump(insights, open(INSIGHTS_LOG, "w"), indent=2)
        print(f"   ✓ Insights saved to seo_insights.json")
        print(f"   Gaps: {len(insights.get('our_gaps', []))} | "
              f"Opportunities: {len(insights.get('keyword_opportunities', []))} | "
              f"Meta fixes: {len(insights.get('meta_title_fixes', []))} | "
              f"Content pushes: {len(insights.get('content_quick_wins', []))}")
    except Exception as e:
        print(f"   ✗ Analysis failed: {e}")
        # Don't crash — seo_bot.py runs fine without insights


if __name__ == "__main__":
    main()
