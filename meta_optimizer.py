#!/usr/bin/env python3
"""
Velluto Meta Description Optimizer
Generates SEO-optimized meta descriptions for all active products, SEO pages,
and blog articles using Claude Haiku + real GSC keyword data, then writes
them back to Shopify.

Run:  python meta_optimizer.py
"""

import os, json, datetime, time, re
import requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

client        = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID       = os.getenv("BLOG_ID", "127785959765")
HEADERS       = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

BASE      = os.path.dirname(os.path.abspath(__file__))
GSC_LOG   = os.path.join(BASE, "gsc_data.json")
META_LOG  = os.path.join(BASE, "meta_optimization_log.json")
USAGE_LOG = os.path.join(BASE, "token_usage.json")

# Pages to skip — legal, B2B deals, internal tools
_SKIP_PAGE_HANDLES = {
    "gdpr-compliance", "general-terms-and-conditions", "legal-notice-and-privacy-policy",
    "refund-policy", "wishlist", "karriere", "bergspezl-b2b-starterpaket",
    "sport2000-bestaetigung", "bike-profi-starterpaket", "sportler-b2b-starterpaket",
    "sport2000", "stradapro-launch-deal-2025", "limited-bundle-deal",
}


# ── Shopify helpers ───────────────────────────────────────────────────────────

def gql(query: str, variables: dict = None) -> dict:
    r = requests.post(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
        headers=HEADERS, json={"query": query, "variables": variables or {}}, timeout=20)
    return r.json().get("data", {})


def clean_html(html: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html or '')).strip()


def fetch_products() -> list[dict]:
    data = gql("""
    {
      products(first: 50, query: "status:active") {
        edges { node {
          id title handle
          description
          seo { title description }
          tags
          productType
        }}
      }
    }""")
    return [e["node"] for e in data.get("products", {}).get("edges", [])]


def _rest(path: str, params: str = "") -> dict:
    r = requests.get(f"https://{SHOPIFY_STORE}/admin/api/2024-01/{path}{params}",
                     headers=HEADERS, timeout=15)
    return r.json()


def _get_meta_desc(resource: str, rid: int) -> str:
    """Fetch existing description_tag metafield value for a resource."""
    data = _rest(f"{resource}/{rid}/metafields.json",
                 "?namespace=global&key=description_tag")
    mfs = data.get("metafields", [])
    return mfs[0]["value"] if mfs else ""


def fetch_pages() -> list[dict]:
    raw = _rest("pages.json", "?limit=50&fields=id,title,handle,body_html")
    pages = []
    for p in raw.get("pages", []):
        if p["handle"] in _SKIP_PAGE_HANDLES:
            continue
        meta = _get_meta_desc("pages", p["id"])
        time.sleep(0.2)
        pages.append({
            "id":    f"rest:page:{p['id']}",
            "_rid":  p["id"],
            "title": p["title"],
            "handle": p["handle"],
            "body":   clean_html(p.get("body_html", ""))[:400],
            "tags":   "",
            "seo":    {"description": meta},
        })
    return pages


def fetch_articles() -> list[dict]:
    BLOG_ID_INT = int(BLOG_ID)
    raw = _rest(f"blogs/{BLOG_ID}/articles.json", "?limit=100&fields=id,title,tags,body_html")
    articles = []
    for a in raw.get("articles", []):
        meta = _get_meta_desc(f"blogs/{BLOG_ID}/articles", a["id"])
        time.sleep(0.2)
        articles.append({
            "id":    f"rest:article:{a['id']}",
            "_rid":  a["id"],
            "title": a["title"],
            "tags":  a.get("tags", ""),
            "body":  clean_html(a.get("body_html", ""))[:300],
            "seo":   {"description": meta},
        })
    return articles


# ── Shopify update functions ──────────────────────────────────────────────────

def update_product_seo(gid: str, meta_desc: str, seo_title: str = None) -> bool:
    seo_input = {"description": meta_desc[:155]}
    if seo_title:
        seo_input["title"] = seo_title
    data = gql("""
    mutation productUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id seo { description } }
        userErrors { field message }
      }
    }""", {"input": {"id": gid, "seo": seo_input}})
    errors = data.get("productUpdate", {}).get("userErrors", [])
    if errors:
        print(f"   ✗ {errors}")
        return False
    return True


def _upsert_metafield(resource: str, rid: int, value: str) -> bool:
    """Create or update the description_tag metafield for a REST resource."""
    meta_payload = {"metafield": {
        "namespace": "global", "key": "description_tag",
        "value": value[:155], "type": "single_line_text_field",
    }}
    r = requests.post(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/{resource}/{rid}/metafields.json",
        headers=HEADERS, json=meta_payload, timeout=15)
    if r.status_code == 201:
        return True
    if r.status_code == 422:
        # Already exists — find it and PUT
        mfs = requests.get(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/{resource}/{rid}/metafields.json"
            "?namespace=global&key=description_tag", headers=HEADERS, timeout=15
        ).json().get("metafields", [])
        if mfs:
            mid = mfs[0]["id"]
            r2 = requests.put(
                f"https://{SHOPIFY_STORE}/admin/api/2024-01/metafields/{mid}.json",
                headers=HEADERS, json={"metafield": {"id": mid, "value": value[:155]}}, timeout=15)
            return r2.status_code == 200
    return False


def update_page_seo(gid: str, meta_desc: str) -> bool:
    rid = int(gid.split(":")[-1])
    return _upsert_metafield("pages", rid, meta_desc)


def update_article_seo(gid: str, meta_desc: str) -> bool:
    rid = int(gid.split(":")[-1])
    return _upsert_metafield(f"blogs/{BLOG_ID}/articles", rid, meta_desc)


# ── Keyword context ───────────────────────────────────────────────────────────

def load_keyword_context() -> str:
    lines = []
    if os.path.exists(GSC_LOG):
        gsc = json.load(open(GSC_LOG))
        top = [r["keys"][0] for r in gsc.get("top_queries", [])[:10] if r.get("impressions", 0) > 5]
        if top:
            lines.append("TOP GOOGLE SEARCH QUERIES (real GSC data — use these terms):\n" +
                         ", ".join(top))
    return "\n".join(lines)


def log_usage(inp: int, out: int):
    today = str(datetime.date.today())
    log = json.load(open(USAGE_LOG)) if os.path.exists(USAGE_LOG) else {}
    e = log.setdefault(today, {"runs": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    e["runs"] += 1; e["input_tokens"] += inp; e["output_tokens"] += out
    cost = (inp * 0.80 + out * 4.0) / 1_000_000
    e["cost_usd"] = round(e["cost_usd"] + cost, 6)
    json.dump(log, open(USAGE_LOG, "w"), indent=2)
    return cost


# ── Meta description generation ───────────────────────────────────────────────

BRAND_CONTEXT = """
Velluto StradaPro cycling glasses: 25g ultralight, UV400 certified, anti-fog,
interchangeable lenses (VellutoPuro clear + VellutoVisione high-contrast),
adjustable nose pads, 30-day risk-free trial, free shipping over €99.
Available in Arancia (orange), Espresso (brown), Nero (black), Viola (purple).
Target market: road cyclists in Netherlands, Germany, Belgium. Price: premium but fair.
Site: velluto-shop.com
"""

def generate_metas(items: list[dict], resource_type: str, kw_context: str) -> list[str]:
    """
    Generate optimized meta descriptions for a batch of items.
    Returns list of meta descriptions in the same order as input items.
    """
    items_text = ""
    for i, item in enumerate(items, 1):
        title   = item.get("title", "")
        content = clean_html(item.get("body") or item.get("contentHtml") or item.get("description") or "")[:300]
        tags    = ", ".join(item.get("tags", [])) if isinstance(item.get("tags"), list) else item.get("tags", "")
        current = (item.get("seo") or {}).get("description", "")
        items_text += f"\n{i}. TITLE: {title}\n   CONTENT EXCERPT: {content}\n   TAGS: {tags}\n   CURRENT META: {current or '(none)'}\n"

    type_instructions = {
        "product": (
            "For products: START with the primary search keyword / product type "
            "(e.g. 'Rennradbrille Anti-Beschlag', 'Road cycling glasses UV400', "
            "'Wielrenbril verwisselbare glazen') — NEVER lead with the brand. "
            "Mention the brand 'Velluto' AFTER the keyword. Add 1-2 differentiators "
            "(25g, UV400, interchangeable lenses, 30-day trial). End with a subtle CTA. "
            "Pattern: '<keyword> – <differentiators>. Velluto <product>, <trust/CTA>.'"
        ),
        "page":    "For pages: match the page's purpose. Include the primary keyword. Be descriptive, not salesy.",
        "article": "For blog articles: summarize the article's value. Include the primary search keyword from the title. Make it compelling to click.",
    }[resource_type]

    prompt = f"""You are an SEO specialist for Velluto (velluto-shop.com), a Dutch road cycling eyewear brand.

BRAND CONTEXT:
{BRAND_CONTEXT}

{kw_context}

TASK: Write an optimized meta description for each item below.
Rules:
- Exactly 140-155 characters (count carefully)
- Include the primary keyword naturally (once)
- Lead with the keyword; the brand name 'Velluto' must appear AFTER the primary keyword, never at the very start
- Make it compelling to click from Google search results
- No keyword stuffing
- Each must be unique — do NOT reuse phrasing across items
- {type_instructions}
- Write in the SAME LANGUAGE as the title (EN/NL/DE)

{items_text}

Return ONLY a JSON array of {len(items)} strings, one per item, in the same order:
["meta 1", "meta 2", ...]"""

    r = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    cost = log_usage(r.usage.input_tokens, r.usage.output_tokens)
    print(f"   Haiku: {r.usage.input_tokens}in/{r.usage.output_tokens}out | ${cost:.4f}")

    raw = r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    metas = json.loads(raw)
    return [m[:155] for m in metas]


def process_batch(items: list[dict], resource_type: str, update_fn, kw_context: str,
                  batch_size: int = 5) -> dict:
    results = {"updated": 0, "skipped": 0, "failed": 0, "items": []}
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        print(f"   Generating batch {i//batch_size + 1}/{(len(items)-1)//batch_size + 1} ({len(batch)} items)...")
        try:
            metas = generate_metas(batch, resource_type, kw_context)
        except Exception as e:
            print(f"   ✗ Generation failed: {e}")
            results["failed"] += len(batch)
            continue

        for item, meta in zip(batch, metas):
            title = item.get("title", "")
            gid   = item["id"]
            old   = (item.get("seo") or {}).get("description", "")
            if old and old == meta:
                results["skipped"] += 1
                continue
            try:
                ok = update_fn(gid, meta)
                if ok:
                    print(f"   ✓ {title[:55]}")
                    print(f"     → {meta}")
                    results["updated"] += 1
                    results["items"].append({"title": title, "meta": meta, "old": old})
                else:
                    results["failed"] += 1
            except Exception as e:
                print(f"   ✗ Update failed for {title}: {e}")
                results["failed"] += 1
            time.sleep(0.4)  # Shopify rate limit

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n🔍 Velluto Meta Optimizer — {datetime.date.today()}")
    print("=" * 55)

    kw_context = load_keyword_context()
    if kw_context:
        print("   GSC keyword context loaded ✓")
    else:
        print("   ⚠️  No GSC data found — run seo_optimizer.py first for best results")

    log = {"date": str(datetime.date.today()), "products": {}, "pages": {}, "articles": {}}

    # ── Products ──────────────────────────────────────────────────────────────
    print("\n🛍️  Fetching active products...")
    products = [p for p in fetch_products() if "StradaPro" in p["title"]
                or "Lens" in p["title"] or "Bidon" in p["title"]
                or "Hard Case" in p["title"] or "Cleaning" in p["title"]]
    print(f"   {len(products)} SEO-relevant products found")
    log["products"] = process_batch(products, "product", update_product_seo, kw_context)

    # ── Pages ─────────────────────────────────────────────────────────────────
    print("\n📄 Fetching SEO pages...")
    pages = fetch_pages()
    print(f"   {len(pages)} pages to optimize")
    log["pages"] = process_batch(pages, "page", update_page_seo, kw_context)

    # ── Blog articles ─────────────────────────────────────────────────────────
    print("\n📝 Fetching blog articles...")
    articles = fetch_articles()
    print(f"   {len(articles)} articles to optimize")
    log["articles"] = process_batch(articles, "article", update_article_seo, kw_context)

    # ── Summary ───────────────────────────────────────────────────────────────
    total_updated = sum(log[k]["updated"] for k in ["products", "pages", "articles"])
    total_failed  = sum(log[k]["failed"]  for k in ["products", "pages", "articles"])
    print(f"\n✅ Done — {total_updated} updated, {total_failed} failed")

    existing = json.load(open(META_LOG)) if os.path.exists(META_LOG) else []
    existing.append(log)
    json.dump(existing, open(META_LOG, "w"), indent=2)
    print(f"   Results saved to meta_optimization_log.json")


if __name__ == "__main__":
    main()
