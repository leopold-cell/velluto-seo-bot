#!/usr/bin/env python3
"""
Velluto SEO Bot — Daily blog automation
Quality-first: validates images, links, and language consistency before publishing.
"""

import os, json, datetime, random, re, requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID       = os.getenv("BLOG_ID", "127785959765")
API_KEY       = os.getenv("ANTHROPIC_API_KEY")

client = Anthropic(api_key=API_KEY)
USAGE_LOG  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token_usage.json")
TOPIC_LOG  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topics_used.json")
IMAGES_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images_used.json")

SHOPIFY_HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}


# ── Verified brand facts (updated from Shopify product data) ─────────────────
# NEVER write anything that contradicts these facts.
BRAND_FACTS = """
VELLUTO — VERIFIED PRODUCT FACTS (do not deviate from these):

STRADAPRO GLASSES (available in 4 colours: Arancia/orange, Espresso/brown, Nero/black, Viola/purple):
- Italian design, high-performance functionality
- UV400 protection — certified eye safety, blocks 100% UVA and UVB
- Ultra-lightweight: 25 grams
- Adjustable nose pads — secure fit, zero pressure on long rides
- Built-in anti-fog system — clear vision on climbs and in variable weather
- Compatible with VellutoPuro and VellutoVisione interchangeable lenses (click-in, tool-free)
- 30-day risk-free trial — test on real rides
- Free shipping on orders over €99

VellutoPuro TRANSPARENT LENS:
- Optimised for road cyclists: ideal protection against wind and insects
- UV400 certified — 100% UVA and UVB protection
- Anti-fog performance
- Click-in system: fast, secure, tool-free lens swap
- 100% compatible with Velluto StradaPro

VellutoVisione™ HIGH CONTRAST LENS:
- VellutoVisione™ technology: instantly sharpens contrast and visual definition
- UV400 certified protection
- Click-in system: lens swap in seconds
- 100% compatible with Velluto StradaPro

ACCESSORIES:
- Hard Case: anti-crash guarantee, fits all road cycling glasses, luxurious velvet finish
- Microfiber Cleaning Cloth: 25×25cm, 80% polyester / 20% polyamide
- Cleaning Spray: 50ml, apple fragrance, refillable, made in Germany
- TACX Bidon (Limited Edition): 500ml, dishwasher safe up to 40°C, made in Netherlands

WHAT VELLUTO DOES NOT OFFER — NEVER WRITE THESE:
✗ Photochromic / self-tinting lenses
✗ Polarized lenses
✗ Prescription lenses / optical inserts
✗ Mirrored lenses (not mentioned in product range)
✗ Multiple lens tints beyond Puro (clear) and Visione (high contrast)
"""

# ── Ogilvy & Schwartz copywriting principles ─────────────────────────────────
COPY_PRINCIPLES = """
COPYWRITING PRINCIPLES (David Ogilvy + Eugene Schwartz):

OGILVY:
1. The headline must promise a specific, desirable benefit — not cleverness.
2. Be concrete and specific. "25 grams" beats "ultra-light". Specificity builds trust.
3. Write to one real person, not a crowd.
4. Never use superlatives without proof ("best", "number one" — back it up or cut it).
5. Testimonials and social proof convert. Weave in cyclist scenarios, not abstract claims.
6. The opening paragraph must pull the reader in. If it's boring, they're gone.

SCHWARTZ:
1. You don't create desire — you channel mass desire that already exists.
   Cyclists already want: to go faster, suffer less, see better, look good on the bike.
2. Match awareness level: these readers KNOW cycling glasses exist. They're deciding WHICH and WHY.
3. Build desire progressively — each paragraph deepens the want before the sell.
4. The product must feel inevitable by the time the CTA arrives.
5. Stack specific proof: weight, UV rating, anti-fog tech — specifics create belief.

RESULT: Every post must feel like advice from a faster, more experienced cycling friend
— not a sales pitch. The product mention should feel like a natural recommendation,
not an interruption.
"""


# ── Token tracking ───────────────────────────────────────────────────────────

_MODEL_COSTS = {
    "claude-opus-4-7":           (15.0, 75.0),
    "claude-sonnet-4-6":         (3.0,  15.0),
    "claude-haiku-4-5-20251001": (0.80,  4.0),
}

def log_usage(inp: int, out: int, model: str = "claude-sonnet-4-6") -> float:
    today = str(datetime.date.today())
    log = json.load(open(USAGE_LOG)) if os.path.exists(USAGE_LOG) else {}
    e = log.setdefault(today, {"runs": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    e["runs"] += 1; e["input_tokens"] += inp; e["output_tokens"] += out
    ip, op = _MODEL_COSTS.get(model, (3.0, 15.0))
    cost = (inp * ip + out * op) / 1_000_000
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

# ── Approved image whitelist ─────────────────────────────────────────────────
# Keyed by filename (without extension) for Claude to match against topic.
WHITELIST = {
    "brown1":                    "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/brown1.webp?v=1776868549",
    "002":                       "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/002.webp?v=1776868548",
    "004":                       "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/004_1462e923-4e9b-497f-a0a0-0f58cb98b84a.webp?v=1776868548",
    "003":                       "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/003.webp?v=1776868548",
    "Rick_Arancia":              "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Rick_Arancia.webp?v=1776855699",
    "Review_19":                 "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_19.webp?v=1776854998",
    "Review_18":                 "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_18.jpg?v=1776852440",
    "visioneexplained":          "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/visioneexplained.webp?v=1776851525",
    "purplestats":               "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/purplestats.webp?v=1776851523",
    "offerpurple":               "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/offerpurple.webp?v=1776851522",
    "Review_16":                 "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_16.webp?v=1776851056",
    "Review_17":                 "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_17.webp?v=1776851053",
    "Review_12":                 "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_12.webp?v=1776851049",
    "Review_6":                  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_6.webp?v=1776851050",
    "Review_7":                  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_7.webp?v=1776851050",
    "Review_10":                 "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_10.webp?v=1776851050",
    "Review_5":                  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_5.webp?v=1776851050",
    "Review_3":                  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_3.webp?v=1776851050",
    "Review_9":                  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_9.webp?v=1776851049",
    "Review_13":                 "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_13.webp?v=1776851048",
    "Review_4":                  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_4.webp?v=1776851048",
    "Review_1":                  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_1.webp?v=1776851050",
    "Review_2":                  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_2.webp?v=1776851048",
    "Review_14":                 "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_14.webp?v=1776851049",
    "testimonialmob7":           "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/testimonialmob7.webp?v=1776794573",
    "image00012":                "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/image00012.jpg?v=1776695290",
    "Hero-mobile-v2":            "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Hero-mobile-v2.webp?v=1776419818",
    "Hero-mobile":               "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Hero-mobile.webp?v=1776355362",
    "Lifestyle_1x1":             "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Lifestyle_1x1_fe573806-27fe-4b9d-8be3-be91c2f1aadb.webp?v=1775581088",
    "TransparentMale":           "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/TransparentMale.webp?v=1775574512",
    "productbrown":              "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/productbrown.webp?v=1776792355",
    "productorange":             "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/productorange.webp?v=1776792409",
    "productblack":              "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/productblack.webp?v=1776792135",
    "productblackmale":          "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/productblackmale.webp?v=1776792135",
    "productorangemale":         "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/productorangemale.webp?v=1776792409",
    "productbrownfemale":        "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/productbrownfemale.webp?v=1776792355",
    "VellutoModelMale002":       "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/VellutoModelMale002.webp?v=1775213817",
    "FooterExportsPeople":       "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/FooterExportsPeople.webp?v=1775212054",
    "Lifestylestudiomobile":     "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Lifestylestudiomobile.webp?v=1775138516",
    "Lifestyle_mobileUGC":       "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Lifestyle_mobileUGC.webp?v=1775138102",
    "FooterExports_Female":      "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/FooterExports_Female.webp?v=1775138042",
    "BuildtoPerform":            "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/BuildtoPerformEditedv2Mobile.webp?v=1775081368",
    "VellutoAboutUs":            "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/VellutoAboutUs.webp?v=1775037042",
    "AllGlasses":                "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/AllGlasses.webp?v=1774979597",
    "LifestyleSection_Transparent": "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/LifestyleSection_Transparent.webp?v=1774975640",
    "LifestyleSection_Orange":   "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/LifestyleSection_Orange.webp?v=1774975205",
    "Velluto_BuilttoPerform_Violet": "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Velluto_BuilttoPerform_Mobile_Violet.webp?v=1774970814",
}

# Images that should NOT be used as blog hero (stats, offers, UI graphics)
_EXCLUDE_AS_HERO = {"purplestats", "offerpurple", "visioneexplained"}
HERO_WHITELIST = {k: v for k, v in WHITELIST.items() if k not in _EXCLUDE_AS_HERO}


def pick_image() -> str:
    """Rotate through HERO_WHITELIST shuffled, resetting only when all have been used."""
    used  = json.load(open(IMAGES_LOG)) if os.path.exists(IMAGES_LOG) else []
    pool  = list(HERO_WHITELIST.keys())
    avail = [k for k in pool if k not in used]
    if not avail:
        used, avail = [], pool[:]
    # Pick randomly from the unused half to avoid long streaks of similar shots
    key = random.choice(avail)
    used.append(key)
    json.dump(used, open(IMAGES_LOG, "w"), indent=2)
    print(f"   Cover image: {key}")
    return HERO_WHITELIST[key]


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
    # Awareness / educational — no false product claims possible
    "why UV400 protection matters for road cyclists",
    "how anti-fog cycling glasses work — what to look for",
    "interchangeable lens cycling glasses — are they worth it",
    "how to choose cycling glasses for your face shape",
    "cycling glasses for wind and rain — what to look for",
    "lens categories 0-3 explained for road cyclists",
    "gravel cycling glasses vs road cycling glasses — key differences",
    "how cycling glasses protect against insects, debris and UV",
    "best cycling glasses for long climbs with changing light",
    "why lightweight cycling glasses matter on long rides",
    "how to clean cycling glasses properly without scratching lenses",
    "high contrast lenses for cycling — when you need them",
    "cycling glasses fit guide — adjustable nose pads and frame sizing",
    "best cycling glasses for the Giro and Tour stage conditions",
    "cycling glasses for low light and overcast Dutch weather",
    "what makes road cycling glasses different from regular sunglasses",
    "how to prevent cycling glasses from fogging on cold climbs",
    "clear lens cycling glasses — when and why to use them",
    "the best cycling glasses under €150 in 2026",
    "cycling eye protection — why glasses are non-negotiable equipment",
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

def generate(topic: str, trends: str, cover_url: str, products: list[dict]) -> tuple[dict, str]:

    # Featured glasses: rotate daily through 4 colours
    featured_glasses = get_featured_glasses(products)
    accessories = [p for p in products if "stradapro" not in p["handle"]][:1]
    featured_products = [p for p in [featured_glasses] + accessories if p][:2]

    product_json = json.dumps([{
        "title": p["title"], "url": p["url"], "image": p["image"]
    } for p in featured_products], indent=2)

    system = f"""You are the SEO content manager and lead copywriter for Velluto (velluto-shop.com), \
a premium Dutch road cycling eyewear brand.

{BRAND_FACTS}

{COPY_PRINCIPLES}

WRITING RULES:
1. Every language version must be 100% in that language — no mixed words (brand names Velluto/StradaPro are OK).
2. Each language block starts with a full H1 in that language.
3. Only link to products using the EXACT URLs provided — never invent URLs.
4. Use ONLY the image URLs provided — never invent image URLs.
5. Before writing a single claim about Velluto products, verify it against BRAND_FACTS above.
6. If a topic implies a feature Velluto doesn't have (e.g. photochromic, polarized), \
   reframe honestly: explain the category, then show how Velluto's actual lenses (Puro/Visione) solve the need."""

    user = f"""Date: {datetime.date.today().strftime('%d %B %Y')} | {get_cycling_context()}
Topic: {topic}
Trends: {trends}

KEYWORD STRATEGY — pick ONE long-tail keyword (3-5 words, low-medium competition, buyer intent).
Use it naturally in: H1, opening paragraph, one H2, meta description. Max 4 uses total. No stuffing.

NO IMAGES in the body. The cover image is set separately. Do not write any <img> tags.
Use hyperlinks and product cards only for visual product integration.

PRODUCTS (EXACT URLs only — never invent):
{product_json}

Write 3 language versions (550-700 words each):

<h1>[Contains long-tail keyword naturally]</h1>
<p>[Intro — {get_cycling_context()} hook, keyword appears here]</p>
<h2>[Core cyclist problem]</h2>
<p>[2-3 expert paragraphs]</p>
<h2>[What to look for — practical checklist]</h2>
<h2>[Why Velluto]</h2>
[Product card:
<div style="border:2px solid #111;border-radius:8px;padding:20px;margin:24px 0;max-width:340px;">
  <img src="PRODUCT_IMAGE_URL" alt="PRODUCT_TITLE" style="max-width:160px;border-radius:6px;margin-bottom:12px;display:block;">
  <strong style="font-size:15px;">PRODUCT_TITLE</strong><br>
  <a href="PRODUCT_URL" style="display:inline-block;margin-top:12px;padding:9px 20px;background:#111;color:#fff;text-decoration:none;border-radius:4px;font-weight:700;">CTA</a>
</div>]
<h2>[FAQ — 3 questions]</h2>
<p>[CTA → https://velluto-shop.com]</p>

RETURN ONLY valid JSON:
{{
  "keyword": "chosen long-tail keyword",
  "title_en": "max 60 chars, contains keyword",
  "meta_description": "max 155 chars English, contains keyword",
  "tags": "ENGLISH ONLY: keyword,cycling glasses,road cycling,Velluto StradaPro",
  "en_html": "complete English HTML",
  "nl_html": "complete Dutch HTML — 100% Dutch",
  "de_html": "complete German HTML — 100% German"
}}"""

    GENERATE_MODEL = "claude-sonnet-4-6"
    response = client.messages.create(
        model=GENERATE_MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}]
    )
    cost = log_usage(response.usage.input_tokens, response.usage.output_tokens, model=GENERATE_MODEL)
    print(f"   Tokens in:{response.usage.input_tokens} out:{response.usage.output_tokens} | ${cost:.4f}")

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]

    post = json.loads(raw)
    print(f"   Keyword: {post.get('keyword', '—')}")
    return post


# ── Quality validation ───────────────────────────────────────────────────────

FORBIDDEN_CLAIMS = [
    (r'photochrom', "claims photochromic lenses — Velluto doesn't offer these"),
    (r'polari[sz]', "claims polarized lenses — Velluto doesn't offer these"),
    (r'prescription|op(tic|tisch)', "claims prescription lenses — not in range"),
    (r'mirror(ed)?(\s+lens)?', "claims mirrored lenses — not in range"),
    (r'tinted?\s+lens', "claims tinted lens beyond Puro/Visione — verify"),
]

def validate(post: dict, products: list[dict]) -> list[str]:
    """Return list of quality issues found."""
    issues = []
    allowed_urls = {p["url"] for p in products} | {"https://velluto-shop.com"}
    all_html = " ".join(post.get(f"{l}_html", "") for l in ["en", "nl", "de"])

    # ── Brand fact-check ──────────────────────────────────────────────────────
    for pattern, msg in FORBIDDEN_CLAIMS:
        if re.search(pattern, all_html, re.IGNORECASE):
            issues.append(f"[FACT] Post {msg}")

    for lang in ["en", "nl", "de"]:
        html = post.get(f"{lang}_html", "")

        # Check language consistency (rough heuristic — brand names are OK)
        if lang == "nl" and re.search(r'\b(the|and|for|with|your)\b', html):
            issues.append(f"[{lang}] May contain English words in Dutch version")
        if lang == "de" and re.search(r'\b(the|and|for|with)\b', html):
            issues.append(f"[{lang}] May contain English words in German version")

        # Check all hrefs are in allowed list
        hrefs = re.findall(r'href="(https?://[^"]+)"', html)
        for href in hrefs:
            if not any(href.startswith(base) for base in allowed_urls):
                issues.append(f"[{lang}] Unrecognised link: {href}")

        # No inline images allowed in body — cover only
        if re.search(r'<img\b', html):
            issues.append(f"[{lang}] Inline <img> tag found — body must be text/links only")

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
        sep = "&" if "?" in featured_url else "?"
        payload["article"]["image"] = {"src": f"{featured_url}{sep}width=1200&height=800&crop=center"}

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

    print("🖼️  Selecting cover image...")
    cover_url = pick_image()

    print("✍️  Generating content...")
    post = generate(topic, trends, cover_url, products)

    print("🔍 Quality check...")
    for attempt in range(2):
        issues = validate(post, products)
        fact_issues = [i for i in issues if i.startswith("[FACT]")]
        other_issues = [i for i in issues if not i.startswith("[FACT]")]

        if fact_issues and attempt == 0:
            print(f"   ✗ Brand fact violation — regenerating ({', '.join(fact_issues)})")
            post = generate(topic, trends, cover_url, products)
            continue

        if issues:
            print("   ⚠️  Minor issues:")
            for iss in other_issues:
                print(f"      - {iss}")
        else:
            print("   ✅ All checks passed")
        break

    body_html = build_article_html(post["en_html"], post["nl_html"], post["de_html"])

    print("📤 Publishing...")
    publish(
        title=post["title_en"],
        body_html=body_html,
        meta_desc=post["meta_description"],
        tags=post["tags"],
        featured_url=cover_url
    )

    print_usage()
    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
