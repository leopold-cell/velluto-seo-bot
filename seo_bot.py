#!/usr/bin/env python3
"""
Velluto SEO Bot — Daily blog automation
Quality-first: validates images, links, and language consistency before publishing.
"""

import os, json, datetime, random, re, requests, time, urllib.parse
from anthropic import Anthropic
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID       = os.getenv("BLOG_ID", "127785959765")
API_KEY       = os.getenv("ANTHROPIC_API_KEY")

client       = Anthropic(api_key=API_KEY)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
USAGE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token_usage.json")
TOPIC_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topics_used.json")

SHOPIFY_HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}


# ── Token tracking ───────────────────────────────────────────────────────────

def log_usage(inp: int, out: int) -> float:
    today = str(datetime.date.today())
    log = json.load(open(USAGE_LOG)) if os.path.exists(USAGE_LOG) else {}
    e = log.setdefault(today, {"runs": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    e["runs"] += 1; e["input_tokens"] += inp; e["output_tokens"] += out
    cost = (inp * 15 + out * 75) / 1_000_000
    e["cost_usd"] = round(e["cost_usd"] + cost, 6)
    json.dump(log, open(USAGE_LOG, "w"), indent=2)
    return cost


def print_usage():
    if not os.path.exists(USAGE_LOG): return
    log = json.load(open(USAGE_LOG))
    total = sum(v["cost_usd"] for v in log.values())
    today = log.get(str(datetime.date.today()), {}).get("cost_usd", 0)
    days = sorted(log.keys())[-7:]
    avg = sum(log[d]["cost_usd"] for d in days) / len(days)
    print(f"\n💰 Cost — Today: ${today:.4f} | 7-day avg: ${avg:.4f} | Total: ${total:.4f}")


# ── Shopify data ─────────────────────────────────────────────────────────────

def graphql(query: str) -> dict:
    r = requests.post(f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
                      headers=SHOPIFY_HEADERS, json={"query": query}, timeout=15)
    return r.json().get("data", {})


# ── AI image generation ──────────────────────────────────────────────────────

# Velluto brand style — appended to every image prompt for visual consistency
BRAND_STYLE = (
    "RAW photo, shot on Sony A7R V with 85mm f/1.4 lens, "
    "real photograph, ultra-realistic, 8K UHD, photojournalism quality, "
    "natural golden hour sunlight, shallow depth of field, "
    "sharp focus on subject, realistic skin and material textures, "
    "muted warm film tones, premium Italian cycling lifestyle. "
    "Must look like a real published magazine photograph — "
    "no CGI, no illustration, no AI artefacts, no text, no logos, no watermarks."
)

def build_image_prompt(topic: str, cycling_context: str, shot: str = "wide") -> str:
    """Ask Claude to write a vivid DALL-E 3 subject prompt; brand style is appended separately."""
    shot_desc = (
        "wide editorial shot: road cyclist in scenic Italian or Dutch landscape, wearing sunglasses"
        if shot == "wide" else
        "tight close-up detail: premium cycling sunglasses on a surface or being held, beautiful light"
    )
    r = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        messages=[{"role": "user", "content":
            f"Write a subject description (max 30 words) for a DALL-E 3 image. "
            f"Blog topic: '{topic}'. Season: {cycling_context}. Shot: {shot_desc}. "
            f"Describe only the subject and scene — no style words. Return ONLY the description."}]
    )
    log_usage(r.usage.input_tokens, r.usage.output_tokens)
    subject = r.content[0].text.strip().strip('"')
    return f"{subject}. {BRAND_STYLE}"


def generate_and_upload_image(topic: str, cycling_context: str, shot: str = "wide") -> str | None:
    """Generate an image via DALL-E 3 and upload it to Shopify CDN."""
    prompt = build_image_prompt(topic, cycling_context, shot)
    print(f"   Prompt: {prompt[:90]}")

    print("   Generating with DALL-E 3...")
    try:
        try:
            # Try gpt-image-1 first (most realistic, requires model access)
            import base64
            response = openai_client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size="1024x1024",
                quality="high",
                n=1,
            )
            img_bytes = base64.b64decode(response.data[0].b64_json)
        except Exception:
            # Fallback to DALL-E 3
            response = openai_client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="hd",
                n=1,
            )
            img_resp = requests.get(response.data[0].url, timeout=30)
            img_bytes = img_resp.content
        return upload_image_to_shopify(img_bytes, prompt[:50])
    except Exception as e:
        print(f"   ✗ DALL-E 3 error: {e}")
        return None



def upload_image_to_shopify(image_bytes: bytes, label: str) -> str | None:
    """Upload raw image bytes to Shopify CDN using staged upload."""
    # Step 1: request a staged upload target
    stage_query = """
    mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets {
          url
          resourceUrl
          parameters { name value }
        }
        userErrors { field message }
      }
    }"""
    variables = {"input": [{"filename": "blog-ai-image.jpg", "mimeType": "image/jpeg",
                             "fileSize": str(len(image_bytes)), "resource": "IMAGE",
                             "httpMethod": "POST"}]}
    data = graphql_with_vars(stage_query, variables)
    targets = data.get("stagedUploadsCreate", {}).get("stagedTargets", [])
    if not targets:
        print("   ✗ Staged upload target failed")
        return None

    target = targets[0]
    upload_url = target["url"]
    resource_url = target["resourceUrl"]
    params = {p["name"]: p["value"] for p in target["parameters"]}

    # Step 2: POST image to the S3/GCS target
    files = {"file": ("blog-ai-image.jpg", image_bytes, "image/jpeg")}
    upload_resp = requests.post(upload_url, data=params, files=files, timeout=30)
    if upload_resp.status_code not in (200, 201, 204):
        print(f"   ✗ Upload to storage failed: {upload_resp.status_code}")
        return None

    # Step 3: register the file in Shopify
    create_query = """
    mutation fileCreate($files: [FileCreateInput!]!) {
      fileCreate(files: $files) {
        files { id fileStatus ... on MediaImage { image { url } } }
        userErrors { field message }
      }
    }"""
    create_vars = {"files": [{"originalSource": resource_url, "contentType": "IMAGE",
                               "alt": f"Velluto cycling glasses — {label}"}]}
    create_data = graphql_with_vars(create_query, create_vars)
    files_created = create_data.get("fileCreate", {}).get("files", [])
    if not files_created:
        print("   ✗ File registration failed")
        return None

    # Poll until file is READY (Shopify processes async)
    file_id = files_created[0]["id"]
    for _ in range(10):
        time.sleep(3)
        poll = graphql(f'{{ node(id: "{file_id}") {{ ... on MediaImage {{ image {{ url }} fileStatus }} }} }}')
        node = poll.get("node", {})
        if node.get("fileStatus") == "READY":
            url = node.get("image", {}).get("url", "")
            print(f"   ✓ AI image on CDN: ...{url[-40:]}")
            return url
    print("   ✗ Image processing timed out")
    return None


def graphql_with_vars(query: str, variables: dict) -> dict:
    r = requests.post(f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
                      headers=SHOPIFY_HEADERS,
                      json={"query": query, "variables": variables}, timeout=30)
    return r.json().get("data", {})


# Only active products, only cycling glasses + relevant accessories
ALLOWED_HANDLES = {
    "velluto-stradapro-cycling-glasses-arancia",
    "velluto-stradapro-cycling-glasses-espresso",
    "velluto-stradapro-cycling-glasses-nero",
    "velluto-stradapro-cycling-glasses-viola",
    "vellutopuro-interchangeable-lenses",
    "velluto-visione-interchangeable-lenses",
    "velluto-hard-case",
    "velluto-microfiber-cleaning-cloth",
    "velluto-drinking-bottle-limited-edition",
    "velluto-cleaning-spray",
}

def get_products() -> list[dict]:
    r = requests.get(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"
        "?limit=50&published_status=published&fields=id,title,handle,status,image",
        headers=SHOPIFY_HEADERS, timeout=15)
    products = []
    for p in r.json().get("products", []):
        if p.get("status") != "active": continue
        if p["handle"] not in ALLOWED_HANDLES: continue
        img = p.get("image", {}).get("src", "") if p.get("image") else ""
        products.append({
            "title":  p["title"],
            "handle": p["handle"],
            "url":    f"https://velluto-shop.com/products/{p['handle']}",
            "image":  img,
        })
    return products


def verify_product_url(url: str) -> bool:
    """Check that a product URL returns 200."""
    try:
        r = requests.get(url, timeout=8, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False


def get_cdn_images() -> list[dict]:
    """Return only lifestyle/glasses DSC shoot images from CDN."""
    data = graphql('{ files(first: 100, query: "media_type:IMAGE") { edges { node { ... on MediaImage { image { url } } } } } }')
    results = []
    for e in data.get("files", {}).get("edges", []):
        url = e.get("node", {}).get("image", {}).get("url", "")
        if not url: continue
        fname = url.split("/")[-1].split("?")[0].lower()
        # Only DSC lifestyle photos from photo shoots
        if fname.startswith("dsc"):
            results.append({"url": url, "filename": fname})
    return results


def pick_lifestyle_images(cdn_images: list[dict], n: int = 2) -> list[str]:
    """Pick n random DSC lifestyle images — these are always contextually appropriate."""
    pool = [img["url"] for img in cdn_images]
    if not pool:
        return []
    return random.sample(pool, min(n, len(pool)))


# ── Cycling context ──────────────────────────────────────────────────────────

def get_cycling_context() -> str:
    return {
        1:  "Winter training, Mallorca cycling camps, Zwift indoor season",
        2:  "Omloop Het Nieuwsblad, Kuurne-Brussel-Kuurne approaching",
        3:  "Milan-Sanremo, E3 Saxo Bank Classic, spring classics",
        4:  "Ronde van Vlaanderen, Paris-Roubaix, Amstel Gold Race, Liège-Bastogne-Liège",
        5:  "Giro d'Italia, gravel season, Alpe d'HuZes NL",
        6:  "Tour de Suisse, Critérium du Dauphiné, summer gravel rides",
        7:  "Tour de France, Dutch cycling camps in Alps & Pyrenees",
        8:  "Vuelta a España, late summer sportives",
        9:  "Vuelta, gravel season peak, autumn sportives NL",
        10: "Il Lombardia, autumn cycling NL, end-of-season rides",
        11: "Cyclocross season, winter preparation",
        12: "Cyclocross peak, holiday gifts for cyclists"
    }[datetime.date.today().month]


TOPIC_POOL = [
    "photochromic cycling glasses vs regular lenses — when to use which",
    "why cyclists should not use polarized sunglasses on the road",
    "best cycling glasses for low light and overcast weather",
    "how to choose cycling glasses for your face shape",
    "cycling glasses that don't fog up — tips and features to look for",
    "interchangeable lens cycling glasses — are they worth it",
    "how to clean cycling glasses properly without scratching lenses",
    "UV400 protection in cycling glasses — what it means and why it matters",
    "best cycling glasses for long climbs with changing light conditions",
    "cycling glasses for wind and rain — what to look for",
    "lens categories 0-3 explained for cyclists",
    "gravel cycling glasses vs road cycling glasses — what's the difference",
    "how cycling glasses protect against insects, debris and UV",
    "best cycling glasses for the Giro and Tour stage types",
    "high contrast lenses for cycling — what they do and when you need them",
]


GLASSES_ROTATION = [
    "velluto-stradapro-cycling-glasses-nero",
    "velluto-stradapro-cycling-glasses-viola",
    "velluto-stradapro-cycling-glasses-espresso",
    "velluto-stradapro-cycling-glasses-arancia",
]

def get_unused_topic() -> str:
    used = json.load(open(TOPIC_LOG)) if os.path.exists(TOPIC_LOG) else []
    available = [t for t in TOPIC_POOL if t not in used]
    if not available:
        used, available = [], TOPIC_POOL[:]
    topic = random.choice(available)
    used.append(topic)
    json.dump(used, open(TOPIC_LOG, "w"), indent=2)
    return topic


def get_featured_glasses(products: list[dict]) -> dict | None:
    """Rotate through the 4 StradaPro colours day by day."""
    day_index = datetime.date.today().toordinal() % len(GLASSES_ROTATION)
    target_handle = GLASSES_ROTATION[day_index]
    for p in products:
        if p["handle"] == target_handle:
            return p
    return next((p for p in products if "stradapro" in p["handle"]), None)


# ── Trend search ─────────────────────────────────────────────────────────────

def search_trends() -> str:
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for q in ["wielrenbril 2026 nieuws", "road cycling glasses 2026"]:
                for h in list(ddgs.text(q, max_results=3)):
                    results.append(f"- {h.get('title','')}: {h.get('body','')[:100]}")
        return "\n".join(results[:5])
    except Exception as e:
        return f"(unavailable: {e})"


# ── Language switcher HTML ───────────────────────────────────────────────────

def build_article_html(en: str, nl: str, de: str) -> str:
    """Wrap 3 language blocks in a tab switcher. Each block must start with its own H1."""
    style = """<style>
.vl-tabs{display:flex;gap:8px;margin:0 0 32px 0}
.vl-tabs button{padding:8px 20px;border:2px solid #1a1a1a;background:none;cursor:pointer;
  font-weight:700;border-radius:4px;font-size:13px;letter-spacing:.3px;transition:all .15s}
.vl-tabs button.on{background:#1a1a1a;color:#fff}
.vl-block{display:none}
.vl-block.on{display:block}
.vl-block h1{font-size:1.9em;font-weight:800;line-height:1.25;margin:0 0 20px}
</style>"""
    js = """<script>
function vl(l){
  ['en','nl','de'].forEach(function(x){
    document.getElementById('vl-'+x).className='vl-block'+(x===l?' on':'');
    document.getElementById('vl-b'+x).className=(x===l?'on':'');
  });
}
</script>"""
    return f"""{style}{js}
<div class="vl-tabs">
  <button id="vl-ben" class="on" onclick="vl('en')">EN</button>
  <button id="vl-bnl" onclick="vl('nl')">NL</button>
  <button id="vl-bde" onclick="vl('de')">DE</button>
</div>
<div id="vl-en" class="vl-block on">{en}</div>
<div id="vl-nl" class="vl-block">{nl}</div>
<div id="vl-de" class="vl-block">{de}</div>"""


# ── Content generation ───────────────────────────────────────────────────────

def generate(topic: str, trends: str, ai_images: list[str], products: list[dict]) -> tuple[dict, str]:

    img1_url = ai_images[0] if len(ai_images) > 0 else ""

    def itag(url, alt):
        return f'<img src="{url}" alt="{alt}" style="max-width:100%;width:100%;border-radius:8px;margin:28px 0;display:block;">' if url else ""

    # Featured glasses: rotate daily through 4 colours
    featured_glasses = get_featured_glasses(products)
    accessories = [p for p in products if "stradapro" not in p["handle"]][:1]
    featured_products = [p for p in [featured_glasses] + accessories if p][:2]

    product_json = json.dumps([{
        "title": p["title"], "url": p["url"], "image": p["image"]
    } for p in featured_products], indent=2)

    system = (
        "You are the SEO content manager for Velluto (velluto-shop.com), "
        "a premium Dutch road cycling eyewear brand. "
        "Voice: expert cyclist, passionate, premium Dolce Vita lifestyle. "
        "Natural writing — no keyword stuffing. Deep knowledge of Dutch cycling culture and races. "
        "CRITICAL RULES: "
        "1. Every language version must be 100% consistent in that language — no mixed words. "
        "2. Each language block must start with a full H1 title in that language. "
        "3. Only link to products using the exact URLs provided — never invent URLs. "
        "4. Include product images using the exact image URLs provided. "
        "5. Use ONLY the lifestyle image URLs provided — do not invent image URLs."
    )

    img1_tag_en = itag(img1_url, f"Velluto road cycling glasses — {topic[:40]}")
    img1_tag_nl = itag(img1_url, f"Velluto wielrenbril — {topic[:40]}")
    img1_tag_de = itag(img1_url, f"Velluto Rennradbrille — {topic[:40]}")

    user = f"""Date: {datetime.date.today().strftime('%d %B %Y')} | {get_cycling_context()}
Topic: {topic}
Trends: {trends}

BLOG IMAGE (use EXACT URL, place after intro paragraph):
{img1_url}

PRODUCTS TO FEATURE (use EXACT URLs and image URLs — do not invent any URLs):
{product_json}

Write the blog post in 3 complete language versions.
Each version (550-700 words) must follow this structure:

<h1>[Title in this language — SEO-optimised, includes main keyword]</h1>
<p>[Engaging intro — hooks with current race season: {get_cycling_context()}]</p>
{img1_tag_en} ← EN version: insert this exact HTML tag here
(for NL use: {img1_tag_nl})
(for DE use: {img1_tag_de})
<h2>[Core problem or question cyclists have]</h2>
<p>[Expert explanation, 2-3 paragraphs]</p>
<h2>[Expert advice: what to look for]</h2>
<p>[Practical checklist or criteria]</p>
<h2>[Why Velluto — 1 featured product card]</h2>
[Insert product card HTML — EXACT values from product JSON:
<div style="border:2px solid #111;border-radius:8px;padding:20px;margin:24px 0;max-width:340px;">
  <img src="EXACT_PRODUCT_IMAGE_URL" alt="PRODUCT_TITLE" style="max-width:160px;border-radius:6px;margin-bottom:12px;display:block;">
  <strong style="font-size:15px;">PRODUCT_TITLE</strong><br>
  <a href="EXACT_PRODUCT_URL" style="display:inline-block;margin-top:12px;padding:9px 20px;background:#111;color:#fff;text-decoration:none;border-radius:4px;font-weight:700;">SHOP_CTA_IN_THIS_LANGUAGE</a>
</div>]
<h2>[FAQ — 3 questions cyclists ask about this topic]</h2>
<p>[CTA → https://velluto-shop.com]</p>

RETURN ONLY valid JSON (no markdown, no code blocks):
{{
  "title_en": "SEO title in English, max 60 chars",
  "meta_description": "max 155 chars in English",
  "tags": "ENGLISH ONLY tags: tag1,tag2,cycling glasses,road cycling,StradaPro",
  "en_html": "complete English HTML",
  "nl_html": "complete Dutch HTML — 100% Dutch including headings and CTA",
  "de_html": "complete German HTML — 100% German including headings and CTA"
}}"""

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}]
    )
    cost = log_usage(response.usage.input_tokens, response.usage.output_tokens)
    print(f"   Tokens in:{response.usage.input_tokens} out:{response.usage.output_tokens} | ${cost:.4f}")

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]

    post = json.loads(raw)
    return post, img1_url


# ── Quality validation ───────────────────────────────────────────────────────

def validate(post: dict, products: list[dict]) -> list[str]:
    """Return list of quality issues found."""
    issues = []
    allowed_urls = {p["url"] for p in products} | {"https://velluto-shop.com"}

    for lang in ["en", "nl", "de"]:
        html = post.get(f"{lang}_html", "")

        # Check language consistency (rough heuristic)
        if lang == "nl" and re.search(r'\b(the|and|for|with|your)\b', html):
            issues.append(f"[{lang}] May contain English words in Dutch version")
        if lang == "de" and re.search(r'\b(the|and|for|with)\b', html):
            issues.append(f"[{lang}] May contain English words in German version")

        # Check all hrefs are in allowed list
        hrefs = re.findall(r'href="(https?://[^"]+)"', html)
        for href in hrefs:
            if not any(href.startswith(base) for base in allowed_urls):
                issues.append(f"[{lang}] Unrecognised link: {href}")

        # Check no invented image URLs (must contain cdn.shopify.com)
        img_srcs = re.findall(r'<img[^>]+src="(https?://[^"]+)"', html)
        for src in img_srcs:
            if "cdn.shopify.com" not in src:
                issues.append(f"[{lang}] Non-CDN image URL: {src[:80]}")

        # Check H1 present
        if "<h1" not in html.lower():
            issues.append(f"[{lang}] Missing H1 heading")

    return issues


# ── Publish ──────────────────────────────────────────────────────────────────

def publish(title: str, body_html: str, meta_desc: str, tags: str, featured_url: str) -> int | None:
    payload = {"article": {
        "title":     title,
        "body_html": body_html,
        "published": True,
        "tags":      tags,
        "metafields": [{"key": "description_tag", "value": meta_desc[:155],
                        "type": "single_line_text_field", "namespace": "global"}]
    }}
    if featured_url:
        payload["article"]["image"] = {"src": featured_url}

    r = requests.post(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json",
        headers=SHOPIFY_HEADERS, json=payload, timeout=20)
    if r.status_code == 201:
        aid = r.json()["article"]["id"]
        print(f"   ✓ Published: {title} (ID: {aid})")
        return aid
    print(f"   ✗ Failed {r.status_code}: {r.text[:300]}")
    return None


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n🚴 Velluto SEO Bot — {datetime.date.today()}")
    print("=" * 50)

    print("📡 Searching trends...")
    trends = search_trends()

    print("🛍️  Fetching active products...")
    products = get_products()
    print(f"   {len(products)} active products")

    topic = get_unused_topic()
    print(f"📝 Topic: {topic}")

    cycling_ctx = get_cycling_context()

    print("🎨 Generating AI image with DALL-E 3...")
    ai_images = []
    url = generate_and_upload_image(topic, cycling_ctx, "wide")
    if url:
        ai_images.append(url)
    print(f"   {len(ai_images)} AI image ready")

    print("✍️  Generating content...")
    post, featured_url = generate(topic, trends, ai_images, products)

    print("🔍 Quality check...")
    issues = validate(post, products)
    if issues:
        print("   ⚠️  Issues found:")
        for iss in issues:
            print(f"      - {iss}")
        print("   Proceeding with caution — review the post manually.")
    else:
        print("   ✅ All checks passed")

    body_html = build_article_html(post["en_html"], post["nl_html"], post["de_html"])

    print("📤 Publishing...")
    publish(
        title=post["title_en"],
        body_html=body_html,
        meta_desc=post["meta_description"],
        tags=post["tags"],
        featured_url=featured_url
    )

    print_usage()
    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
