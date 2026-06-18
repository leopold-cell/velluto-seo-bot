#!/usr/bin/env python3
"""
Velluto SEO Bot — Daily blog automation
Quality-first: validates images, links, and language consistency before publishing.
"""

import os, json, datetime, random, re, requests, time, traceback
from anthropic import Anthropic
from dotenv import load_dotenv

# Phase 1: dynamic commercial config (prices, UVP, offers per market).
# See ~/velluto-seo-bot/commercial_config.py — pulls live data from Shopify and
# overrides per market (NL is currently testing 69 EUR).
from commercial_config import load_commercial_config, for_market, safe_price_str  # noqa: E402


def retry(max_attempts=3, delay=8, label=""):
    """Exponential-backoff retry decorator for flaky API calls."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            name = label or fn.__name__
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts:
                        raise
                    wait = delay * (2 ** (attempt - 1))
                    print(f"   ⚠️  {name} failed (attempt {attempt}/{max_attempts}): {e} — retrying in {wait}s")
                    time.sleep(wait)
        return wrapper
    return decorator

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID       = os.getenv("BLOG_ID", "127785959765")
API_KEY       = os.getenv("ANTHROPIC_API_KEY")

client = Anthropic(api_key=API_KEY)
USAGE_LOG      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token_usage.json")
TOPIC_LOG      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topics_used.json")
IMAGES_LOG     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images_used.json")
DYNAMIC_LOG    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topics_dynamic.json")
INSIGHTS_LOG   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seo_insights.json")
PUBLISHED_LOG  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "published_today.json")
QUALITY_LOG    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quality_level.json")
NL_KW_LOG      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nl_keywords_used.json")
ARTICLE_NUM_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "article_num.json")

# All shop locales that receive T&A market adaptations.
# EN is the Shopify primary locale — the primary article is published in English directly.
# DE and all other markets get locale-specific adaptations via Shopify Translate & Adapt.
SHOP_LOCALES = ["de", "nl", "fr", "es", "it", "da", "nb", "pl", "pt-PT", "sv"]

# Human-readable language name per locale (for Haiku prompts)
LOCALE_LANG_NAMES = {
    "de":    "German",
    "nl":    "Dutch",
    "en":    "English",
    "fr":    "French",
    "es":    "Spanish",
    "it":    "Italian",
    "da":    "Danish",
    "nb":    "Norwegian",
    "pl":    "Polish",
    "pt-PT": "Portuguese",
    "sv":    "Swedish",
}

# Local cycling context hints per locale (improves adaptation quality)
# Includes verified local competitor brands for "alternative to X" content angles
LOCALE_CYCLING_CONTEXT = {
    "de":    "German cycling culture, Rennradszene, Alpenpass-Touren, Radklassiker, ISPO-Neuheiten; "
             "local competitors: Uvex (DE market leader, sportstyle.de), Alpina (mid-range DE brand); "
             "retailers: Bike24 (Leipzig), Rose Bikes, Fahrrad.de; media: Rennrad-News.de, Tour-Magazin.de",
    "nl":    "Dutch cycling culture, polderroutes, wielrennen; local brands: AGU, Shimano NL; "
             "retailers: Cyclingworld, Fietsportaal",
    "en":    "UK/international cycling context, sportives, British cycling; "
             "local brands: Oakley, Endura; retailers: Wiggle, Chain Reaction",
    "fr":    "French cycling culture, vélo de route, Tour de France, cols alpins; "
             "local competitors: Julbo (premium FR brand), Ekoï (direct-to-consumer FR), "
             "Van Rysel/Decathlon (budget dominance); retailer: Alltricks.fr",
    "es":    "Spanish cycling culture, ciclismo en carretera, Vuelta, Sierra Nevada, Pyreneos; "
             "local competitors: Spiuk (ES market leader, calidad-precio), "
             "Eassun (photochromic specialist); retailer: Lordgun, Decathlon.es",
    "it":    "Italian cycling culture, ciclismo su strada, Giro d'Italia, Dolomiti, Lago di Garda, "
             "Strade Bianche; local competitors: Rudy Project (Italian premium, da vista specialist), "
             "Salice (photochromic mid-market), Briko; retailer: Gambacicli.com",
    "da":    "Danish cycling culture, landevejscykling, Bornholm, danske cykelruter; "
             "local competitors: KOO (growing), Oakley stockists (Heino Cykler); "
             "retailers: Cykelexperten.dk, Cykelgear.dk; opticians: Synoptik, Profil Optik",
    "nb":    "Norwegian cycling culture, landeveissykling, fjordroutes, Birkebeinerrittet; "
             "local competitors: Sweet Protection (strong NO brand, Falline model), "
             "POC (Swedish, massive in Scandinavia); retailers: Bikable.no; media: Landevei.no",
    "pl":    "Polish cycling culture, kolarstwo szosowe, Bieszczady, Tatry, Wisła; "
             "local competitors: GOG Eyewear / Goggle (Polish brand from Poznań, Prostaf — "
             "market leader in domestic sporting eyewear); retailers: CentrumRowerowe.pl, Bikeworld.pl",
    "pt-PT": "Portuguese cycling culture, ciclismo de estrada, Algarve, Serra da Estrela, "
             "Volta a Portugal; local competitors: Spiuk (via spiuk-portugal.com), "
             "Bertoni (Italian brand with PT e-commerce); opticians: MaisOptica.pt, MultiOpticas",
    "sv":    "Swedish cycling culture, landsvägscykling, Vätternrundan, Göta Kanal, fjällvägar; "
             "local competitors: Bliz Active Eyewear (Swedish, affordable market leader, 2.5M/year), "
             "POC (Swedish premium, Clarity/Zeiss lenses); retailers: Cykelkraft.se; media: Happyride.se",
}


def load_seo_insights(topic: str = "") -> str:
    """Load SEO optimizer output as a prompt injection. Adds comparison guidelines if topic is a vs-post."""
    if not os.path.exists(INSIGHTS_LOG):
        return ""
    try:
        ins = json.load(open(INSIGHTS_LOG))
        parts = []
        if ins.get("next_post_guidelines"):
            parts.append("WRITING GUIDELINES FROM SEO ANALYSIS:\n" +
                         "\n".join(f"• {g}" for g in ins["next_post_guidelines"]))
        if ins.get("keyword_opportunities"):
            parts.append("KEYWORD OPPORTUNITIES TO COVER:\n" +
                         "\n".join(f"• {k}" for k in ins["keyword_opportunities"]))
        if ins.get("seo_quick_wins"):
            parts.append("SEO QUICK WINS TO APPLY:\n" +
                         "\n".join(f"• {w}" for w in ins["seo_quick_wins"]))
        if ins.get("meta_title_fixes"):
            parts.append("META TITLE IMPROVEMENTS (real Google CTR data — apply these patterns):\n" +
                         "\n".join(f"• {f}" for f in ins["meta_title_fixes"]))
        if ins.get("content_quick_wins"):
            parts.append("CONTENT DEPTH TARGETS (real Google impression data — topics needing richer posts):\n" +
                         "\n".join(f"• {w}" for w in ins["content_quick_wins"]))
        if ins.get("geo_angles"):
            parts.append("GEO/AI VISIBILITY ANGLES:\n" +
                         "\n".join(f"• {a}" for a in ins["geo_angles"]))
        # Inject comparison-specific guidance if this is a vs-post
        if "vs" in topic.lower() and ins.get("comparison_post_angles"):
            competitor = topic.split("vs")[0].strip().split()[-1]  # e.g. "Oakley"
            angle = next((a for a in ins["comparison_post_angles"]
                          if competitor.lower() in a.lower()), None)
            if angle:
                parts.append(
                    f"COMPARISON POST STRATEGY (from competitor analysis):\n• {angle}\n"
                    "• Frame as 'why cyclists switch to Velluto' — not an attack on the competitor\n"
                    "• Lead with Velluto's concrete specs: 25g, UV400, 30-day trial, interchangeable lenses\n"
                    "• Target search intent: people comparing before buying\n"
                    "• Include a side-by-side section highlighting key differentiators\n"
                    "• CTA: '30-day risk-free trial — try it on your next ride'"
                )
        return "\n\n".join(parts)
    except Exception:
        return ""

SHOPIFY_HEADERS   = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def notify(msg: str):
    """Send a Telegram message. Silently skips if credentials missing."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception:
        pass


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

CRITICAL — NEVER CLAIM THIS:
✗ The StradaPro is NOT suitable to wear over normal prescription glasses (Over-Glasses use).
  Do NOT write: "fits over", "passt über", "over your glasses", "über der Brille",
  "Brillenträger können", "for glasses wearers", or any similar phrasing.
  The StradaPro is designed to be worn on its own, not as an over-glasses frame.

✗ Do NOT discuss prescription glasses as an alternative or mention that Velluto lacks a
  prescription option. Avoid the topic entirely — do not reference it even negatively.
  If glasses-wearers come up naturally, redirect to fit and lens versatility:
  "The StradaPro fits a wide range of face shapes and comes with interchangeable
   clear and high-contrast lenses for varying light conditions."
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
    # Phase 4.6 — May 2026 outdoor shoot (10 lifestyle photos, _5 intentionally omitted)
    "Shooting_Outdoors_May_2026_1":  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Shooting_Outdoors_May_2026_1.png?v=1779885436",
    "Shooting_Outdoors_May_2026_2":  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Shooting_Outdoors_May_2026_2.png?v=1779885435",
    "Shooting_Outdoors_May_2026_3":  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Shooting_Outdoors_May_2026_3.png?v=1779885435",
    "Shooting_Outdoors_May_2026_4":  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Shooting_Outdoors_May_2026_4.png?v=1779885436",
    "Shooting_Outdoors_May_2026_6":  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Shooting_Outdoors_May_2026_6.png?v=1779885435",
    "Shooting_Outdoors_May_2026_7":  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Shooting_Outdoors_May_2026_7.png?v=1779885435",
    "Shooting_Outdoors_May_2026_8":  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Shooting_Outdoors_May_2026_8.png?v=1779885435",
    "Shooting_Outdoors_May_2026_9":  "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Shooting_Outdoors_May_2026_9.png?v=1779885436",
    "Shooting_Outdoors_May_2026_10": "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Shooting_Outdoors_May_2026_10.png?v=1779885436",
    "Shooting_Outdoors_May_2026_11": "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Shooting_Outdoors_May_2026_11.png?v=1779885436",
}

# Images that should NOT be used as blog hero (stats, offers, UI graphics)
_EXCLUDE_AS_HERO = {"purplestats", "offerpurple", "visioneexplained"}

# Images confirmed too small for a 1200×800 cover (would be upscaled → blurry/oversized)
# Dimensions from scan: Rick_Arancia=534×626, Review_2=1024×1365, Review_14=670×803
_TOO_SMALL_FOR_HERO = {"Rick_Arancia", "Review_2", "Review_14"}

HERO_WHITELIST = {k: v for k, v in WHITELIST.items()
                  if k not in _EXCLUDE_AS_HERO and k not in _TOO_SMALL_FOR_HERO}

# Categorise so 3 daily posts always rotate across visually distinct image types
IMAGE_CATEGORIES = {
    "review":    ["Review_1","Review_3","Review_4","Review_5","Review_6",
                  "Review_7","Review_9","Review_10","Review_12","Review_13",
                  "Review_16","Review_17","Review_18","Review_19","testimonialmob7","image00012"],
    "lifestyle": ["TransparentMale","VellutoModelMale002","FooterExportsPeople",
                  "FooterExports_Female","Lifestylestudiomobile","Lifestyle_mobileUGC",
                  "Lifestyle_1x1","LifestyleSection_Transparent","LifestyleSection_Orange",
                  "Velluto_BuilttoPerform_Violet","Hero-mobile-v2","Hero-mobile","brown1",
                  # Phase 4.6 — May 2026 outdoor shoot
                  "Shooting_Outdoors_May_2026_1","Shooting_Outdoors_May_2026_2",
                  "Shooting_Outdoors_May_2026_3","Shooting_Outdoors_May_2026_4",
                  "Shooting_Outdoors_May_2026_6","Shooting_Outdoors_May_2026_7",
                  "Shooting_Outdoors_May_2026_8","Shooting_Outdoors_May_2026_9",
                  "Shooting_Outdoors_May_2026_10","Shooting_Outdoors_May_2026_11"],
    "product":   ["productblack","productblackmale","productorange","productorangemale",
                  "productbrown","productbrownfemale","AllGlasses","BuildtoPerform",
                  "VellutoAboutUs","002","003","004"],
}
# Cycle: review → lifestyle → product → review → …
_CAT_ORDER = ["review", "lifestyle", "product"]


def pick_image() -> str:
    """
    Rotate through categories (review/lifestyle/product) so consecutive posts
    never look similar. Within each category, shuffle without repeating.
    State is persisted in images_used.json.
    """
    state = json.load(open(IMAGES_LOG)) if os.path.exists(IMAGES_LOG) else {"used": [], "cat_index": 0}
    if isinstance(state, list):          # migrate old format
        state = {"used": state, "cat_index": 0}

    cat_index = state.get("cat_index", 0) % len(_CAT_ORDER)
    category  = _CAT_ORDER[cat_index]
    pool      = [k for k in IMAGE_CATEGORIES[category] if k in HERO_WHITELIST]
    used      = state.get("used", [])
    avail     = [k for k in pool if k not in used]
    if not avail:                         # all used in this category — reset just this category
        used  = [k for k in used if k not in pool]
        avail = pool[:]

    key = random.choice(avail)
    used.append(key)
    state = {"used": used, "cat_index": (cat_index + 1) % len(_CAT_ORDER)}
    json.dump(state, open(IMAGES_LOG, "w"), indent=2)
    print(f"   Cover image: {key} [{category}]")
    return HERO_WHITELIST[key]


def pick_cover(topic: str, keyword: str | None = None) -> str:
    """Cover image for a post. Try a fresh AI-generated, topic-specific image
    (hosted on Shopify Files); fall back to the curated rotation pool so the
    bot never fails on image issues."""
    try:
        import image_generator
        url = image_generator.generate_cover(topic, keyword or topic)
        if url:
            return url
    except Exception as e:
        print(f"   ⚠️  AI cover gen failed ({e}); using curated pool")
    return pick_image()


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

@retry(max_attempts=3, delay=5, label="get_products")
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
    # UV & lens technology
    "why UV400 protection matters for road cyclists",
    "lens categories 0-3 explained for road cyclists",
    "high contrast lenses for cycling — when you need them",
    "clear lens cycling glasses — when and why to use them",
    "how anti-fog coating works on cycling glasses",
    "VellutoVisione high contrast lens review for road cyclists",
    "transparent cycling lens vs tinted lens — complete guide",
    "UV400 vs UV380 cycling glasses — what is the difference",
    # Anti-fog & weather
    "how anti-fog cycling glasses work — what to look for",
    "how to prevent cycling glasses from fogging on cold climbs",
    "cycling glasses for wind and rain — what to look for",
    "cycling glasses for low light and overcast Dutch weather",
    "best cycling glasses for autumn rides in the Netherlands",
    "winter cycling glasses guide — what to look for",
    "cycling glasses for early morning rides — low light tips",
    # Fit & comfort
    "cycling glasses fit guide — adjustable nose pads and frame sizing",
    "how to choose cycling glasses for your face shape",
    "why lightweight cycling glasses matter on long rides",
    "cycling glasses that don't slip — what to look for",
    "cycling glasses for small faces — fit guide 2026",
    "best cycling glasses for long distance sportives",
    "cycling glasses for narrow faces — a buyers guide",
    # Interchangeable lenses
    "interchangeable lens cycling glasses — are they worth it",
    "how to swap cycling glass lenses in under 10 seconds",
    "best interchangeable lens cycling glasses 2026",
    "click-in lens system cycling glasses — what to look for",
    "cycling glasses with two lenses — complete buying guide",
    # Road cycling specific
    "gravel cycling glasses vs road cycling glasses — key differences",
    "how cycling glasses protect against insects, debris and UV",
    "best cycling glasses for long climbs with changing light",
    "cycling glasses for the Giro d'Italia — what the pros use",
    "best cycling glasses for the Tour de France stage conditions",
    "cycling glasses for criteriums — speed and clarity",
    "cycling glasses for gran fondos — the complete guide",
    "road cycling glasses for beginners — what you need to know",
    # Buying guides & comparisons
    "the best cycling glasses under €150 in 2026",
    "cycling glasses under €100 — worth it or not",
    "what makes road cycling glasses different from regular sunglasses",
    "cycling eye protection — why glasses are non-negotiable equipment",
    "how to clean cycling glasses properly without scratching lenses",
    "best cycling glasses for wide heads 2026",
    "cycling glasses buying guide — 10 things to check",
    "cycling glasses vs ski goggles — key differences explained",
    # Dutch & NL market
    "de beste wielrenbril van 2026 — koopgids",
    "wielrenbril met verwisselbare glazen — wat je moet weten",
    "anti-condens wielrenbril — hoe werkt het",
    "wielrenbril voor brede gezichten — pasgids",
    "sportbril voor wielrennen — UV bescherming uitgelegd",
    "wielrenbril voor slechte weersomstandigheden — Nederland",
    "beste wielrenbril onder 150 euro in 2026",
    "wielrenbril voor de Amstel Gold Race — wat te kiezen",
    # Competitor comparison (educational angle)
    "POC cycling glasses vs budget alternatives — honest comparison",
    "Oakley cycling glasses — are premium brands worth the price",
    "cycling glasses brands compared — what to look for in 2026",
    "why expensive cycling glasses are not always better",
    # Seasonal & event-driven
    "cycling glasses for spring classics — Ronde van Vlaanderen tips",
    "best cycling glasses for summer heat and bright sun",
    "cycling glasses gift guide for road cyclists 2026",
    "new cycling glasses for the new season — what changed in 2026",
]


GLASSES_ROTATION = [
    "velluto-stradapro-cycling-glasses-nero",
    "velluto-stradapro-cycling-glasses-viola",
    "velluto-stradapro-cycling-glasses-espresso",
    "velluto-stradapro-cycling-glasses-arancia",
]

def research_new_topics() -> list[str]:
    """Use DuckDuckGo trends + Claude Haiku to discover 3 fresh blog topics daily."""
    existing_dynamic = json.load(open(DYNAMIC_LOG)) if os.path.exists(DYNAMIC_LOG) else []
    all_known = TOPIC_POOL + existing_dynamic
    try:
        from ddgs import DDGS
        snippets = []
        with DDGS() as ddgs:
            for q in ["cycling glasses trend 2026", "wielrenbril review 2026", "best sports glasses cyclists"]:
                for h in list(ddgs.text(q, max_results=3)):
                    snippets.append(f"{h.get('title','')}: {h.get('body','')[:100]}")
        context = "\n".join(snippets[:8])
    except Exception:
        context = "cycling glasses, road cycling eyewear, UV protection, anti-fog lenses"

    r = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content":
            f"Trending cycling search context:\n{context}\n\n"
            f"Already covered topics (DO NOT repeat):\n{all_known[-20:]}\n\n"
            "Suggest 3 NEW blog post topics for a cycling glasses brand targeting Dutch road cyclists. "
            "Focus on what people are actively searching for: buyer intent, comparisons, how-tos, seasonal. "
            "Return ONLY a JSON array of 3 strings."}]
    )
    log_usage(r.usage.input_tokens, r.usage.output_tokens, model="claude-haiku-4-5-20251001")
    try:
        raw = r.content[0].text.strip()
        if raw.startswith("```"): raw = raw.split("```")[1].lstrip("json").strip()
        new_topics = json.loads(raw)
        merged = list(dict.fromkeys(existing_dynamic + new_topics))  # dedup, preserve order
        json.dump(merged, open(DYNAMIC_LOG, "w"), indent=2)
        print(f"   Discovered {len(new_topics)} new topics: {new_topics}")
        return new_topics
    except Exception as e:
        print(f"   ⚠️  Topic research parse failed: {e}")
        return []


def get_unused_topic() -> str:
    """Pick an unused topic from static pool + dynamically discovered topics."""
    used = json.load(open(TOPIC_LOG)) if os.path.exists(TOPIC_LOG) else []
    dynamic = json.load(open(DYNAMIC_LOG)) if os.path.exists(DYNAMIC_LOG) else []
    full_pool = list(dict.fromkeys(TOPIC_POOL + dynamic))  # static first, then dynamic
    available = [t for t in full_pool if t not in used]
    if not available:
        used, available = [], full_pool[:]
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


ARTICLE_CSS = """
  /* ── Velluto Magazine Article — self-contained, scoped under .vl ── */
  /* Full-viewport breakout from any Shopify article container        */
  .vl{
    width:100vw;
    position:relative;
    left:50%;
    transform:translateX(-50%);
    overflow-x:hidden;
    background:#f5f4f1;
    color:#0a0a0a;
    font-family:'Manrope','Helvetica Neue',Helvetica,Arial,sans-serif;
    font-size:16px;line-height:1.55;
    -webkit-font-smoothing:antialiased;
    text-rendering:optimizeLegibility;
    --bg:#f5f4f1;--bg-2:#ebeae5;--ink:#0a0a0a;--ink-2:#1b1b1b;--mute:#8b8a85;
    --hair:#0a0a0a14;--hair-strong:#0a0a0a26;--paper:#ffffff;
    --sans:'Manrope','Helvetica Neue',Helvetica,Arial,sans-serif;
  }
  .vl *,.vl *::before,.vl *::after{box-sizing:border-box;margin:0;padding:0}
  .vl img{max-width:100%;display:block}
  .vl a{color:inherit}
  /* ── Shell ── */
  .vl .wrap{max-width:1400px;margin:0 auto;padding:0 32px}
  @media(max-width:1080px){.vl .wrap{padding:0 24px}}
  @media(max-width:720px){.vl .wrap{padding:0 18px}}
  @media(max-width:480px){.vl .wrap{padding:0 16px}}
  /* ── Hero ── */
  .vl .hero{padding:64px 0 0}
  .vl .hero-eyebrow{font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);font-weight:600;margin-bottom:24px;display:inline-flex;gap:10px;align-items:center;}
  .vl .hero-eyebrow::before{content:"";width:24px;height:1px;background:var(--ink);display:inline-block;}
  .vl .hero-title{font-family:var(--sans);font-weight:600;font-size:clamp(40px,6.4vw,92px);line-height:1.0;letter-spacing:-0.035em;color:var(--ink);max-width:18ch;text-wrap:balance;}
  .vl .hero-title em{font-style:italic;font-weight:500;font-family:Georgia,'Times New Roman',serif;letter-spacing:-0.02em;}
  .vl .hero-sub{margin-top:28px;font-size:18px;line-height:1.5;color:var(--ink-2);max-width:50ch;font-weight:400;}
  .vl .hero-meta-bottom{margin-top:64px;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:24px;padding:24px 0;border-top:1px solid var(--hair-strong);border-bottom:1px solid var(--hair-strong);}
  .vl .hero-meta-bottom div{display:flex;flex-direction:column;gap:6px}
  .vl .hero-meta-bottom dt{font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);font-weight:600;}
  .vl .hero-meta-bottom dd{font-size:14px;color:var(--ink);font-weight:500}
  /* Hero figure — full bleed inside .vl .wrap (negative margins cancel the 32px padding) */
  .vl .hero-figure{margin:48px -32px 0;aspect-ratio:16/9;background:var(--bg-2);overflow:hidden;position:relative;}
  .vl .hero-figure img{width:100%;height:100%;object-fit:cover;filter:grayscale(1) contrast(1.02);}
  .vl .hero-figure .credit{position:absolute;left:24px;bottom:18px;font-size:10.5px;letter-spacing:.18em;text-transform:uppercase;color:#fff;font-weight:500;mix-blend-mode:difference;}
  /* ── Mobile TOC (replaces sidebar on phones) ── */
  .vl .toc-mobile{display:none}
  /* ── Article grid ── */
  .vl .article{display:grid;grid-template-columns:220px 1fr 220px;gap:48px;padding:80px 0 48px;align-items:start;}
  @media(max-width:1080px){.vl .article{grid-template-columns:180px 1fr;gap:32px}.vl .article aside.right{display:none}}
  @media(max-width:760px){.vl .article{grid-template-columns:1fr;gap:0;padding:48px 0}.vl .article aside.left,.vl .article aside.right{display:none}}
  /* ── TOC sidebar ── */
  .vl aside.left{position:sticky;top:120px}
  .vl .toc-head{font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);margin-bottom:18px;font-weight:600;}
  .vl .toc{list-style:none;display:flex;flex-direction:column;gap:0;border-top:1px solid var(--hair)}
  .vl .toc li{border-bottom:1px solid var(--hair)}
  .vl .toc a{display:flex;gap:12px;padding:11px 0;font-size:13px;color:var(--ink-2);text-decoration:none;line-height:1.35;align-items:flex-start;transition:padding-left .2s;}
  .vl .toc a span.num{font-size:10px;color:var(--mute);font-weight:600;flex-shrink:0;width:20px;padding-top:2px;letter-spacing:.08em;}
  .vl .toc a:hover,.vl .toc a.active{padding-left:4px;color:var(--ink)}
  .vl .toc a.active span.num{color:var(--ink)}
  .vl .toc a.active{font-weight:600}
  /* ── Article body ── */
  .vl article{max-width:680px;margin:0 auto}
  .vl article > * + *{margin-top:20px}
  .vl article p{font-size:17px;line-height:1.6;color:var(--ink-2);font-weight:400;text-wrap:pretty;}
  .vl article p.lede{font-size:clamp(20px,1.8vw,24px);line-height:1.45;color:var(--ink);font-weight:400;margin-bottom:36px;}
  .vl article h2{font-family:var(--sans);font-weight:600;font-size:clamp(26px,2.8vw,34px);line-height:1.1;letter-spacing:-0.025em;color:var(--ink);margin-top:64px;margin-bottom:8px;padding-top:28px;border-top:1px solid var(--hair-strong);scroll-margin-top:140px;text-wrap:balance;}
  .vl article h2 .sec-num{display:block;font-size:11px;color:var(--mute);letter-spacing:.22em;font-weight:600;margin-bottom:14px;text-transform:uppercase;}
  .vl article h2 em{font-style:italic;font-weight:500;font-family:Georgia,'Times New Roman',serif;}
  .vl article h3{font-family:var(--sans);font-weight:600;font-size:18px;letter-spacing:-0.01em;color:var(--ink);margin-top:20px;}
  .vl article a.inline{color:var(--ink);font-weight:600;text-decoration:none;background-image:linear-gradient(var(--ink),var(--ink));background-size:100% 1px;background-position:0 100%;background-repeat:no-repeat;padding-bottom:1px;transition:background-size .25s;}
  .vl article a.inline:hover{background-size:0% 1px;background-position:100% 100%}
  .vl article strong{color:var(--ink);font-weight:700}
  .vl article ul,.vl article ol{padding-left:0;list-style:none;border-top:1px solid var(--hair);margin-top:12px}
  .vl article ul li,.vl article ol li{position:relative;padding:16px 0 16px 56px;border-bottom:1px solid var(--hair);font-size:16px;color:var(--ink-2);line-height:1.55;}
  .vl article ul li::before{content:"";position:absolute;left:18px;top:25px;width:18px;height:1px;background:var(--ink);}
  .vl article ol{counter-reset:listcount}
  .vl article ol li{counter-increment:listcount}
  .vl article ol li::before{content:counter(listcount,decimal-leading-zero);position:absolute;left:0;top:16px;font-size:11px;letter-spacing:.12em;color:var(--ink);font-weight:700;}
  .vl article ul li strong,.vl article ol li strong{color:var(--ink);font-weight:700;display:inline;}
  /* ── Inline figure ── */
  .vl .inline-figure{margin:48px -80px;border:1px solid var(--hair);background:var(--bg-2);overflow:hidden;}
  .vl .inline-figure img{width:100%;aspect-ratio:16/9;object-fit:cover;filter:grayscale(1) contrast(1.03);}
  .vl .inline-figure .cap{padding:14px 20px;display:flex;justify-content:space-between;gap:16px;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--mute);font-weight:500;background:var(--paper);border-top:1px solid var(--hair);}
  .vl .inline-figure .cap span:last-child{text-transform:none;letter-spacing:0;font-style:italic;color:var(--ink-2);font-family:Georgia,serif;font-weight:400;font-size:13px}
  @media(max-width:1080px){.vl .inline-figure{margin:40px 0}}
  /* ── Pull quote ── */
  .vl .pullquote{margin:56px 0;padding:48px 0;border-top:1px solid var(--hair-strong);border-bottom:1px solid var(--hair-strong);text-align:center;}
  .vl .pullquote q{font-family:Georgia,'Times New Roman',serif;font-style:italic;font-weight:400;font-size:clamp(24px,2.8vw,36px);line-height:1.25;color:var(--ink);text-wrap:balance;display:block;letter-spacing:-0.01em;quotes:"\\201C" "\\201D";max-width:24ch;margin:0 auto;}
  .vl .pullquote cite{font-family:var(--sans);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);font-style:normal;font-weight:600;display:block;margin-top:24px;}
  /* ── Criteria grid ── */
  .vl .criteria{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:var(--hair-strong);border:1px solid var(--hair-strong);margin:32px 0;}
  .vl .crit{background:var(--paper);padding:28px 24px;display:flex;flex-direction:column;gap:10px;min-height:180px;}
  .vl .crit .num{font-size:10.5px;color:var(--mute);letter-spacing:.22em;font-weight:700;text-transform:uppercase;}
  .vl .crit h4{font-weight:600;font-size:19px;line-height:1.2;letter-spacing:-0.015em;color:var(--ink);}
  .vl .crit p{font-size:14px;color:var(--ink-2);line-height:1.5;margin-top:auto;}
  @media(max-width:520px){.vl .criteria{grid-template-columns:1fr}}
  /* ── Product card ── */
  .vl .product{margin:64px 0;background:var(--paper);display:grid;grid-template-columns:1fr 1fr;overflow:hidden;border:1px solid var(--hair-strong);box-shadow:0 2px 12px rgba(0,0,0,0.07);}
  .vl .product-media{background:var(--paper);position:relative;aspect-ratio:4/3;overflow:hidden;border-right:1px solid var(--hair-strong);}
  .vl .product-media img{width:100%;height:100%;object-fit:cover;transition:transform .8s ease;}
  .vl .product:hover .product-media img{transform:scale(1.03)}
  .vl .product-tag{position:absolute;top:14px;left:14px;font-size:10px;letter-spacing:.2em;text-transform:uppercase;background:var(--ink);color:#fff;padding:6px 10px;font-weight:600;}
  .vl .product-info{padding:36px 32px;display:flex;flex-direction:column;gap:18px}
  .vl .product-eyebrow{font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);font-weight:600;}
  .vl .product-name{font-weight:600;font-size:28px;line-height:1.1;letter-spacing:-0.025em;color:var(--ink);}
  .vl .product-name em{font-family:Georgia,serif;font-style:italic;font-weight:500;}
  .vl .product-specs{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:18px 0;border-top:1px solid var(--hair);border-bottom:1px solid var(--hair);}
  .vl .spec dt{font-size:10px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);margin-bottom:4px;font-weight:600;}
  .vl .spec dd{font-size:14.5px;color:var(--ink);font-weight:600}
  .vl .product-price{font-size:22px;color:var(--ink);font-weight:600;letter-spacing:-0.015em;}
  .vl .product-price small{font-size:11px;color:var(--mute);letter-spacing:.18em;margin-left:8px;text-transform:uppercase;font-weight:600}
  .vl .product-cta-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .vl .product-cta{display:inline-flex;align-items:center;justify-content:space-between;gap:14px;background:var(--ink);color:#fff;padding:14px 20px;font-weight:600;font-size:13px;text-decoration:none;letter-spacing:.06em;text-transform:uppercase;transition:background .2s,transform .2s;flex:1;min-width:200px;}
  .vl .product-cta:hover{background:#2a2a2a;transform:translateY(-1px)}
  .vl .product-cta svg{width:14px;height:14px;transition:transform .25s}
  .vl .product-cta:hover svg{transform:translateX(3px)}
  .vl .product-cta.secondary{background:transparent;color:var(--ink);border:1px solid var(--ink);flex:0 0 auto}
  .vl .product-cta.secondary:hover{background:var(--ink);color:#fff}
  @media(max-width:680px){.vl .product{grid-template-columns:1fr}.vl .product-media{border-right:none;border-bottom:1px solid var(--hair-strong);aspect-ratio:1/1}.vl .product-info{padding:28px 22px}}
  .vl .product.compact .product-name{font-size:24px}
  .vl .product.compact .product-media{aspect-ratio:1/1}
  /* ── Spec strip ── */
  .vl .spec-strip{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--hair-strong);border-bottom:1px solid var(--hair-strong);margin:48px 0;}
  .vl .spec-strip > div{padding:28px 20px;border-left:1px solid var(--hair);display:flex;flex-direction:column;gap:6px;}
  .vl .spec-strip > div:first-child{border-left:none}
  .vl .spec-strip .big{font-size:46px;line-height:1;letter-spacing:-0.04em;color:var(--ink);display:flex;align-items:baseline;gap:3px;font-weight:600;}
  .vl .spec-strip .big sup{font-size:16px;color:var(--ink);font-weight:500;letter-spacing:0;opacity:.6}
  .vl .spec-strip .lbl{font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);margin-top:8px;font-weight:600;}
  @media(max-width:680px){.vl .spec-strip{grid-template-columns:repeat(2,1fr)}.vl .spec-strip > div:nth-child(3){border-left:none}.vl .spec-strip > div{border-top:1px solid var(--hair)}.vl .spec-strip > div:nth-child(-n+2){border-top:none}}
  /* ── Variants ── */
  .vl .variants{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--hair-strong);margin:40px 0;border:1px solid var(--hair-strong);}
  .vl .variants a{background:var(--paper);display:flex;flex-direction:column;gap:0;text-decoration:none;color:var(--ink);transition:background .2s;}
  .vl .variants a:hover{background:var(--bg)}
  .vl .variants img{aspect-ratio:1/1;width:100%;object-fit:cover;background:#f7f5f0}
  .vl .variants .v-info{padding:14px 16px;display:flex;justify-content:space-between;align-items:baseline;gap:8px}
  .vl .variants .v-name{font-weight:600;font-size:13px;letter-spacing:-0.01em}
  .vl .variants .v-price{font-size:12px;color:var(--mute);font-weight:500}
  @media(max-width:600px){.vl .variants{grid-template-columns:repeat(2,1fr)}}
  /* ── FAQ ── */
  .vl .faq{margin:24px 0 0;border-top:1px solid var(--hair-strong)}
  .vl .faq details{border-bottom:1px solid var(--hair)}
  .vl .faq summary{list-style:none;cursor:pointer;padding:24px 0;display:flex;justify-content:space-between;align-items:flex-start;gap:24px;font-weight:600;font-size:18px;line-height:1.3;color:var(--ink);letter-spacing:-0.015em;transition:color .15s;}
  .vl .faq summary::-webkit-details-marker{display:none}
  .vl .faq summary::after{content:"";display:inline-block;width:14px;height:14px;flex-shrink:0;margin-top:6px;background-image:linear-gradient(var(--ink),var(--ink)),linear-gradient(var(--ink),var(--ink));background-size:14px 1.4px,1.4px 14px;background-position:center;background-repeat:no-repeat;transition:transform .25s;}
  .vl .faq details[open] summary::after{background-size:14px 1.4px,0 0;transform:rotate(180deg);}
  .vl .faq .answer{padding:0 36px 28px 0;font-size:15.5px;line-height:1.6;color:var(--ink-2);animation:vl-fadein .25s ease;}
  @keyframes vl-fadein{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
  /* ── Mobile share strip (visible only ≤760px, below article) ── */
  .vl .mobile-share{display:none}
  /* ── Right sidebar ── */
  .vl aside.right{position:sticky;top:120px;font-size:13px;color:var(--mute)}
  .vl .author-card{padding:0 0 24px;}
  .vl .author-card .avatar{width:48px;height:48px;border-radius:50%;background:#e0dfd9;background-size:cover;background-position:center;margin-bottom:14px;filter:grayscale(1) contrast(1.02);}
  .vl .author-card .role{font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);margin-bottom:6px;font-weight:600;}
  .vl .author-card .name{font-size:16px;color:var(--ink);font-weight:600;letter-spacing:-0.01em}
  .vl .author-card .bio{font-size:12.5px;color:var(--mute);margin-top:8px;line-height:1.5}
  .vl .share{margin-top:28px;padding-top:24px;border-top:1px solid var(--hair)}
  .vl .share-head{font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);margin-bottom:10px;font-weight:600}
  .vl .share-list{display:flex;flex-direction:column;gap:0}
  .vl .share-list a{text-decoration:none;color:var(--ink);font-size:13px;font-weight:500;padding:10px 0;border-bottom:1px solid var(--hair);display:flex;justify-content:space-between;transition:padding .2s;}
  .vl .share-list a:hover{padding-left:4px}
  .vl .share-list a span:last-child{opacity:.4}
  .vl .italian-note{margin-top:28px;padding-top:24px;border-top:1px solid var(--hair);font-family:Georgia,serif;font-style:italic;font-size:14px;line-height:1.5;color:var(--ink-2);}
  .vl .italian-note small{display:block;font-family:var(--sans);font-style:normal;font-weight:600;font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);margin-bottom:8px;}
  /* ── Ride Fast CTA ── */
  .vl .ride{margin:80px 0 0;background:var(--ink);color:#fff;padding:96px 32px;position:relative;overflow:hidden;}
  .vl .ride-inner{max-width:1340px;margin:0 auto;display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:end;}
  .vl .ride h2{font-family:var(--sans);font-weight:600;font-size:clamp(48px,8vw,120px);line-height:.95;letter-spacing:-0.045em;color:#fff;}
  .vl .ride h2 em{font-family:Georgia,serif;font-style:italic;font-weight:500;color:#fff;opacity:.6;}
  .vl .ride p{font-size:15.5px;line-height:1.55;color:#ffffffaa;max-width:42ch;font-weight:300;}
  .vl .ride-cta{display:inline-flex;align-items:center;gap:10px;background:#fff;color:var(--ink);padding:18px 28px;text-decoration:none;font-weight:700;font-size:12.5px;letter-spacing:.1em;text-transform:uppercase;margin-top:24px;transition:background .2s,transform .2s;}
  .vl .ride-cta:hover{background:var(--bg);transform:translateY(-2px)}
  .vl .ride-cta svg{width:14px;height:14px}
  /* ── Reveal animation ── */
  .vl .reveal{opacity:0;transform:translateY(12px);transition:opacity .7s ease,transform .7s ease}
  .vl .reveal.in{opacity:1;transform:none}
  /* ── Responsive — 1080px ── */
  @media(max-width:1080px){
    .vl .hero{padding-top:48px}
    .vl .hero-figure{margin-left:-24px;margin-right:-24px}
    .vl .ride{padding-left:24px;padding-right:24px}
  }
  /* ── Responsive — 720px ── */
  @media(max-width:720px){
    .vl .hero{padding-top:40px}
    .vl .hero-eyebrow{margin-bottom:18px;font-size:10.5px}
    .vl .hero-title{font-size:clamp(34px,9vw,52px);max-width:none}
    .vl .hero-sub{margin-top:20px;font-size:16.5px}
    .vl .hero-meta-bottom{margin-top:36px;padding:18px 0;grid-template-columns:repeat(2,1fr);gap:16px 18px;}
    .vl .hero-meta-bottom dd{font-size:13px}
    .vl .hero-figure{margin:36px -18px 0}
    .vl .hero-figure .credit{left:14px;bottom:12px;font-size:9.5px}
    /* show mobile TOC */
    .vl .toc-mobile{
      display:block;margin:36px -18px 0;background:var(--paper);
      border-top:2px solid var(--ink);border-bottom:1px solid var(--hair-strong);
    }
    .vl .toc-mobile summary{
      list-style:none;cursor:pointer;padding:18px 20px;display:flex;justify-content:space-between;
      align-items:center;font-size:11px;letter-spacing:.22em;text-transform:uppercase;
      color:var(--ink);font-weight:700;min-height:52px;
    }
    .vl .toc-mobile summary::-webkit-details-marker{display:none}
    .vl .toc-mobile summary .count{font-weight:500;color:var(--mute);letter-spacing:.18em;font-size:10.5px;display:flex;align-items:center;gap:10px;}
    .vl .toc-mobile summary .count::after{content:"+";font-size:18px;color:var(--ink);font-weight:300;line-height:1;transition:transform .25s}
    .vl .toc-mobile[open] summary .count::after{transform:rotate(45deg)}
    .vl .toc-mobile ol{list-style:none;border-top:1px solid var(--hair);}
    .vl .toc-mobile li{border-bottom:1px solid var(--hair)}
    .vl .toc-mobile li:last-child{border-bottom:0}
    .vl .toc-mobile a{display:flex;gap:14px;padding:16px 20px;font-size:15px;color:var(--ink);text-decoration:none;line-height:1.35;min-height:52px;align-items:center;}
    .vl .toc-mobile a .n{font-size:11px;color:var(--mute);font-weight:700;letter-spacing:.08em;flex-shrink:0;width:24px;}
    /* article */
    .vl .article{padding:56px 0 32px}
    .vl article > * + *{margin-top:18px}
    .vl article p{font-size:16.5px}
    .vl article p.lede{font-size:19px;margin-bottom:28px}
    .vl article h2{font-size:clamp(24px,6.4vw,30px);margin-top:48px;padding-top:24px;scroll-margin-top:80px;}
    .vl article h2 .sec-num{font-size:10.5px;margin-bottom:10px}
    .vl article ul li,.vl article ol li{padding:14px 0 14px 48px;font-size:16px;min-height:52px;}
    .vl article ul li::before{top:23px;left:16px;width:16px}
    .vl article ol li::before{font-size:10.5px}
    .vl .inline-figure{margin:32px -18px;border-left:0;border-right:0}
    .vl .inline-figure .cap{padding:12px 18px;font-size:10.5px;flex-direction:column;gap:4px;align-items:flex-start}
    .vl .pullquote{margin:36px 0;padding:32px 0}
    .vl .pullquote q{font-size:clamp(22px,6vw,28px);max-width:18ch}
    .vl .pullquote cite{margin-top:18px;font-size:10px}
    .vl .criteria{margin:24px 0;grid-template-columns:1fr}
    .vl .crit{min-height:0;padding:22px 20px}
    .vl .spec-strip{margin:32px 0}
    .vl .spec-strip > div{padding:22px 16px}
    .vl .spec-strip .big{font-size:34px}
    .vl .product{margin:44px 0}
    .vl .product-media{aspect-ratio:4/3}
    .vl .product-info{padding:24px 20px;gap:16px}
    .vl .product-name{font-size:24px}
    .vl .product-specs{padding:14px 0;gap:14px}
    .vl .product-cta-row{flex-direction:column;align-items:stretch}
    .vl .product-cta{flex:0 0 auto;min-width:0;min-height:52px;width:100%;justify-content:space-between;}
    .vl .product-cta.secondary{text-align:center;justify-content:center}
    .vl .variants{margin:28px 0}
    .vl .variants .v-info{padding:12px 14px}
    .vl .faq summary{font-size:16.5px;padding:20px 0;gap:16px;min-height:56px;}
    .vl .faq .answer{padding:0 0 22px;font-size:15.5px}
    /* mobile share strip */
    .vl .mobile-share{
      display:flex;align-items:center;gap:0;margin:40px 0 0;
      border-top:1px solid var(--hair-strong);border-bottom:1px solid var(--hair-strong);
      padding:0;overflow:hidden;
    }
    .vl .mobile-share span{font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--mute);font-weight:600;padding:16px 18px;flex-shrink:0;border-right:1px solid var(--hair);}
    .vl .mobile-share a{flex:1;display:flex;align-items:center;justify-content:center;padding:16px 12px;font-size:12.5px;font-weight:600;text-decoration:none;color:var(--ink);letter-spacing:.06em;text-transform:uppercase;border-right:1px solid var(--hair);min-height:52px;transition:background .2s;}
    .vl .mobile-share a:last-child{border-right:none}
    .vl .mobile-share a:active{background:var(--bg-2)}
    .vl .ride{margin:64px 0 0;padding:64px 18px}
    .vl .ride-inner{grid-template-columns:1fr;gap:20px}
    .vl .ride h2{font-size:clamp(40px,11vw,64px)}
    .vl .ride p{font-size:15px;max-width:none}
    .vl .ride-cta{width:100%;justify-content:space-between;padding:16px 20px;min-height:52px;}
  }
  /* ── Responsive — 480px ── */
  @media(max-width:480px){
    .vl .wrap{padding:0 16px}
    .vl .hero-title{font-size:clamp(30px,10vw,46px);letter-spacing:-0.03em;line-height:1.02}
    .vl .hero-meta-bottom div:nth-child(n+3){display:none}
    .vl .toc-mobile{margin-left:-16px;margin-right:-16px}
    .vl .toc-mobile summary{padding:16px 18px}
    .vl .toc-mobile a{padding:14px 16px;font-size:14.5px}
    .vl .inline-figure{margin-left:-16px;margin-right:-16px}
    .vl article p{font-size:16px}
    .vl article p.lede{font-size:18px}
    .vl .product-info{padding:22px 18px}
    .vl .product-name{font-size:22px}
    .vl .crit{padding:20px 18px}
    .vl .spec-strip > div{padding:18px 14px}
    .vl .spec-strip .big{font-size:32px}
    .vl .mobile-share span{padding:14px 14px}
    .vl .mobile-share a{padding:14px 10px;font-size:12px}
    .vl .ride{padding:48px 20px}
    .vl .ride h2{font-size:clamp(38px,13vw,56px)}
  }
  /* hover only on real hover devices */
  @media(hover:none){
    .vl .product:hover .product-media img{transform:none}
  }
"""

ARTICLE_JS = """
<script>
  // toc active — desktop sidebar + mobile accordion
  const tocLinks = document.querySelectorAll('#toc a, #tocMobile a');
  const sections = [...document.querySelectorAll('article h2')];
  const setActive = () => {
    const y = window.scrollY + 180;
    let active = sections[0]?.id;
    for (const s of sections) { if (s.offsetTop <= y) active = s.id; }
    tocLinks.forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + active));
  };
  document.addEventListener('scroll', setActive, {passive:true});
  setActive();
  // close mobile TOC after tapping a link
  document.querySelectorAll('#tocMobile a').forEach(a => {
    a.addEventListener('click', () => {
      const t = document.getElementById('tocMobile');
      if (t) t.open = false;
    });
  });
  // animated counters
  const animateCount = (el) => {
    const target = parseInt(el.dataset.count, 10);
    const dur = 1100, start = performance.now();
    const step = (t) => {
      const p = Math.min(1, (t - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased).toString();
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  // reveal + counter trigger
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        e.target.classList.add('in');
        e.target.querySelectorAll?.('[data-count]').forEach(animateCount);
        io.unobserve(e.target);
      }
    }
  }, {threshold:0.2});
  document.querySelectorAll('.spec-strip, .criteria, .product, .pullquote, .inline-figure, .variants, .hero-figure, .related-grid').forEach(el => {
    el.classList.add('reveal'); io.observe(el);
  });
  // FAQ accordion — one open at a time
  document.querySelectorAll('.faq details').forEach(d => {
    d.addEventListener('toggle', () => {
      if (d.open) document.querySelectorAll('.faq details').forEach(o => { if (o !== d) o.open = false; });
    });
  });
</script>
"""


def get_season_year() -> str:
    m = datetime.date.today().month
    y = datetime.date.today().year
    if m in (12, 1, 2): return f"Winter {y}"
    if m in (3, 4, 5):  return f"Frühjahr {y}"
    if m in (6, 7, 8):  return f"Sommer {y}"
    return f"Herbst {y}"


# ── Content generation ───────────────────────────────────────────────────────

@retry(max_attempts=3, delay=10, label="generate")
def generate(topic: str, trends: str, cover_url: str, products: list[dict]) -> tuple[dict, str]:

    # Featured glasses: rotate daily through 4 colours
    featured_glasses = get_featured_glasses(products)
    accessories = [p for p in products if "stradapro" not in p["handle"]][:1]
    featured_products = [p for p in [featured_glasses] + accessories if p][:2]

    product_json = json.dumps([{
        "title": p["title"], "url": p["url"], "image": p["image"]
    } for p in featured_products], indent=2)

    seo_insights = load_seo_insights(topic=topic)

    system = f"""You are the SEO content manager and lead copywriter for Velluto (velluto-shop.com), \
a premium Dutch road cycling eyewear brand.

{BRAND_FACTS}

{COPY_PRINCIPLES}
{(chr(10) + seo_insights + chr(10)) if seo_insights else ""}
WRITING RULES:
1. Every language version must be 100% in that language — no mixed words (brand names Velluto/StradaPro are OK).
2. Each language block starts with a full H1 in that language.
3. Only link to products using the EXACT URLs provided — never invent URLs.
4. Use ONLY the image URLs provided — never invent image URLs.
5. Before writing a single claim about Velluto products, verify it against BRAND_FACTS above.
6. Velluto does NOT offer photochromic, polarized, or prescription lenses.
   You MAY discuss these features when comparing to competitors OR in informational/FAQ sections.
   You MUST NOT attribute them to Velluto products.
   ✓ "Oakley's Prizm lenses are polarized; Velluto's interchangeable system gives you control without lock-in to one tint."
   ✗ "The Velluto StradaPro's polarized lenses cut glare..."
7. If a topic implies a feature Velluto doesn't have, reframe honestly: explain the category, then show how Velluto's actual lenses (Puro/Visione) solve the need.
8. NEVER use the em-dash "—" or a spaced en-dash " – " anywhere. Use commas, periods or colons instead. (Normal hyphens in compound words are fine.)"""

    user = f"""Date: {datetime.date.today().strftime('%d %B %Y')} | {get_cycling_context()}
Topic: {topic}
Trends: {trends}

KEYWORD STRATEGY — pick ONE long-tail keyword (3-5 words, low-medium competition, buyer intent).
Use it naturally in: H1, opening paragraph, one H2, meta description. Max 4 uses total. No stuffing.

NO IMAGES in the body. The cover image is set separately. Do not write any <img> tags.
Use hyperlinks and product cards only for visual product integration.

PRODUCTS (EXACT URLs only — never invent):
{product_json}

Write 3 language versions (800-1000 words each — quality over quantity, go deep):

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

Use EXACTLY this output format — delimiters on their own lines, no extra text outside them:

===META===
keyword: <chosen long-tail keyword>
title_en: <max 60 chars, contains keyword>
meta_description: <max 155 chars English, contains keyword>
tags: <ENGLISH ONLY: keyword,cycling glasses,road cycling,Velluto StradaPro>
===EN===
<complete English HTML here>
===NL===
<complete Dutch HTML here — 100% Dutch>
===DE===
<complete German HTML here — 100% German>
===END==="""

    GENERATE_MODEL = "claude-sonnet-4-6"
    response = client.messages.create(
        model=GENERATE_MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}]
    )
    cost = log_usage(response.usage.input_tokens, response.usage.output_tokens, model=GENERATE_MODEL)
    print(f"   Tokens in:{response.usage.input_tokens} out:{response.usage.output_tokens} | ${cost:.4f}")

    raw = response.content[0].text
    post = _parse_response(raw)
    print(f"   Keyword: {post.get('keyword', '—')}")
    return post


def _parse_response(raw: str) -> dict:
    """Parse delimiter-based response — robust against HTML containing quotes or braces."""
    def extract(tag_start, tag_end):
        m = re.search(rf'{re.escape(tag_start)}\n(.*?)\n{re.escape(tag_end)}', raw, re.DOTALL)
        return m.group(1).strip() if m else ""

    meta_block = extract("===META===", "===EN===")
    en_html    = extract("===EN===",   "===NL===")
    nl_html    = extract("===NL===",   "===DE===")
    de_html    = extract("===DE===",   "===END===")

    post = {"en_html": en_html, "nl_html": nl_html, "de_html": de_html}
    for line in meta_block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            post[k.strip()] = v.strip()

    required = {"keyword", "title_en", "meta_description", "tags", "en_html", "nl_html", "de_html"}
    missing = required - set(post.keys())
    if missing or not post.get("en_html"):
        raise ValueError(f"Response missing fields: {missing}. Raw snippet: {raw[:300]}")
    return post


# ── Quality validation ───────────────────────────────────────────────────────

FORBIDDEN_CLAIMS = [
    # Phase 4.4: photochrom + polari[sz] moved to briefs.quality_gate.check_brand_facts
    # for sentence-aware attribution (only flag VELLUTO-attributed claims, not
    # competitor mentions or informational FAQ content).
    #
    # Only block when prescription is directly linked to Velluto/StradaPro or claimed as a product feature
    (r'(velluto|stradapro).{0,60}prescription'
     r'|prescription.{0,30}(lens|lenses|version|option|frame|insert)',
     "claims prescription lenses — not in range"),
    (r'mirror(ed)?(\s+lens)?', "claims mirrored lenses — not in range"),
    (r'tinted?\s+lens', "claims tinted lens beyond Puro/Visione — verify"),
    # StradaPro is NOT an over-glasses frame
    (r'fits?\s+over|passt\s+(über|uber)|over[\s-]glasses|über\s+der\s+Brille|über\s+(deine|ihre|normale)\s+Brille|Brillenträger\s+können|for\s+(prescription\s+)?glasses\s+wear',
     "claims StradaPro fits over prescription glasses — it does not"),
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

@retry(max_attempts=3, delay=5, label="publish")
def publish(title: str, body_html: str, meta_desc: str, tags: str, featured_url: str) -> int | None:
    payload = {"article": {
        "title":           title,
        "body_html":       body_html,
        "published":       True,
        "author":          "Velluto Redaktion",
        "tags":            tags,
        "template_suffix": "velluto-magazine",
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
        art = r.json()["article"]
        aid, handle = art["id"], art.get("handle", "")
        print(f"   ✓ Published: {title} (ID: {aid})")
        return aid, handle
    raise RuntimeError(f"Shopify publish failed {r.status_code}: {r.text[:300]}")


# ── NL GEO Agent — Quality Compounding ──────────────────────────────────────

def get_quality_targets() -> dict:
    """
    Read quality_level.json (day counter) and return writing targets.
    Targets compound +10%/day from Day 1 baseline, capped at Day 30.
    """
    state = json.load(open(QUALITY_LOG)) if os.path.exists(QUALITY_LOG) else {"day": 1}
    day = max(1, min(int(state.get("day", 1)), 30))
    factor = 1.0 + 0.10 * (day - 1)          # Day 1 = 1.0×, Day 7 = 1.6×, Day 14 = 2.3×, Day 30 = 3.9×
    return {
        "day":                day,
        "word_count":         int(900 * factor),         # 900 → 1800+ words
        "faq_count":          min(3 + (day - 1), 9),     # 3 → 9 FAQ questions
        "include_comparison": day >= 5,
        "include_stats":      day >= 3,
        "include_product_table": day >= 7,
    }


def increment_quality_day():
    """Advance the quality day counter by 1."""
    state = json.load(open(QUALITY_LOG)) if os.path.exists(QUALITY_LOG) else {"day": 1}
    state["day"] = state.get("day", 1) + 1
    json.dump(state, open(QUALITY_LOG, "w"), indent=2)


def get_article_number() -> str:
    """Return zero-padded article number (e.g. '001') and increment the counter."""
    state = json.load(open(ARTICLE_NUM_LOG)) if os.path.exists(ARTICLE_NUM_LOG) else {"num": 1}
    n = max(1, int(state.get("num", 1)))
    padded = f"{n:03d}"
    state["num"] = n + 1
    json.dump(state, open(ARTICLE_NUM_LOG, "w"), indent=2)
    return padded


# TODO: replace Claude lookup with Google Keyword Planner API for real volume data
@retry(max_attempts=2, delay=5, label="research_market_keywords")
def research_market_keywords(en_keyword: str) -> dict:
    """
    Given the primary EN keyword, return the best keyword + search intent + volume
    for ALL shop markets (DE + SHOP_LOCALES).

    Flow:
    1. Claude Haiku — picks the best local keyword per market + writes search intent.
       (Language-native selection: Haiku knows what cyclists actually search per country.)
    2. DataForSEO search_volume/live — validates exact monthly volume for each
       Haiku-selected keyword in one batch HTTP call.
    3. Volume attached to each locale entry in the return dict.

    Returns: {"de": {"keyword": ..., "intent": ..., "volume": int}, "nl": {...}, ...}
    Graceful fallback: if DataForSEO is unavailable, falls back to Haiku-only (volume=0).
    """
    # Always include "en" for the primary article keyword, regardless of SHOP_LOCALES
    research_locales = ["en"] + [loc for loc in SHOP_LOCALES if loc != "en"]
    all_locales = ["de"] + research_locales

    # ── Step 1: Claude Haiku — locale-native keyword selection + intent ────────
    locale_list = "\n".join(
        f'  "{loc}": {{"keyword": "...", "intent": "..."}}'
        for loc in all_locales
    )
    HAIKU = "claude-haiku-4-5-20251001"
    r = client.messages.create(
        model=HAIKU,
        max_tokens=1000,
        system="You are an SEO keyword researcher for cycling eyewear. Return ONLY valid JSON, no extra text.",
        messages=[{"role": "user", "content":
            f"Primary EN keyword: {en_keyword}\n\n"
            "For EACH market locale below, find the BEST local search keyword a cyclist would "
            "actually type (NOT a literal translation — use natural local search behaviour and "
            "terminology for that country) and describe the search intent in one sentence.\n\n"
            "Return exactly this JSON structure:\n"
            "{{\n"
            f"{locale_list}\n"
            "}}"
        }]
    )
    log_usage(r.usage.input_tokens, r.usage.output_tokens, model=HAIKU)
    raw = r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    result = json.loads(raw)

    # ── Step 2: Normalise Haiku results ───────────────────────────────────────
    fallback = {"keyword": en_keyword, "intent": "", "volume": 0}
    normalised: dict = {"de": result.get("de", {"keyword": en_keyword, "intent": ""})}
    for loc in research_locales:
        normalised[loc] = result.get(loc, fallback)
    for entry in normalised.values():
        entry.setdefault("volume", 0)

    # ── Step 3: DataForSEO search_volume/live — attach real volumes ───────────
    try:
        from keyword_research import get_search_volumes
        kw_map   = {loc: entry["keyword"] for loc, entry in normalised.items()}
        volumes  = get_search_volumes(kw_map)
        for loc, entry in normalised.items():
            entry["volume"] = volumes.get(loc, 0)
        if volumes:
            print(f"   DataForSEO: volumes attached for {len(volumes)} locales")
    except Exception as e:
        print(f"   ⚠️  DataForSEO volume lookup failed: {e} — continuing without volumes")

    return normalised




# ── DE-primary magazine article generation ───────────────────────────────────

@retry(max_attempts=3, delay=10, label="generate_de_primary")
def generate_de_primary(kw: dict, products: list[dict], quality: dict,
                        commercial: dict | None = None,
                        brief: dict | None = None,
                        retry_feedback: str | None = None) -> dict:
    """
    Generate a full English magazine article using the Velluto HTML template structure.
    Publishes in English (Shopify primary locale). DE/NL/FR etc. are registered via T&A.
    kw must include 'art_num' key (e.g. '014').

    commercial: optional commercial config from load_commercial_config(). When
                provided, the EN-primary template price interpolates the US
                price string (e.g. "$149"). When None, falls back to "$149".
    brief:      optional Phase 4 master brief. When present, augments the prompt
                with must_answer_questions (PAA), claims_to_avoid, and the
                Velluto positioning angle. When None, legacy behaviour.
    """
    # Phase 1: dynamic price for the EN-primary article (US is the EN market).
    primary_market = (commercial or {}).get("US") or {}
    primary_price_str = (
        f"${primary_market.get('current_price')}"
        if primary_market.get("currency") == "USD" and primary_market.get("current_price")
        else "$149"
    )
    keyword_en = kw.get("keyword_en") or kw["keyword"]  # EN keyword is primary
    keyword_de = kw.get("keyword_de") or kw["keyword"]  # DE keyword for context only
    keyword_nl = kw.get("keyword_nl", kw["keyword"])
    keyword    = keyword_en  # primary keyword driving the article
    title_hint = kw.get("title_nl", keyword)
    angle      = kw.get("angle", "")
    art_num    = kw.get("art_num", "001")
    word_count = quality["word_count"]
    faq_count  = quality["faq_count"]

    glasses = get_featured_glasses(products)
    accessories = [p for p in products if "stradapro" not in p["handle"]][:1]
    featured = [p for p in [glasses] + accessories if p][:2]
    product_json = json.dumps([{
        "title": p["title"], "url": p["url"], "image": p["image"]
    } for p in featured], indent=2)

    seo_ctx = load_seo_insights(topic=keyword)

    # Map colours to approved CDN image URLs for the article
    cdn_images_hint = (
        "APPROVED CDN PRODUCT IMAGE URLs (use ONLY these for product images in the article):\n"
        f"  Nero glasses: {WHITELIST.get('productblack','')}\n"
        f"  Nero male model: {WHITELIST.get('productblackmale','')}\n"
        f"  Espresso glasses: {WHITELIST.get('productbrown','')}\n"
        f"  Espresso female model: {WHITELIST.get('productbrownfemale','')}\n"
        f"  Arancia glasses: {WHITELIST.get('productorange','')}\n"
        f"  Arancia male model: {WHITELIST.get('productorangemale','')}\n"
        f"  Viola lifestyle: {WHITELIST.get('Velluto_BuilttoPerform_Violet','')}\n"
        f"  All glasses together: {WHITELIST.get('AllGlasses','')}\n"
        f"  Lifestyle male: {WHITELIST.get('VellutoModelMale002','')}\n"
        f"  Lifestyle female: {WHITELIST.get('FooterExports_Female','')}\n"
    )

    season = get_season_year()
    cycling_ctx = get_cycling_context()

    # Phase 4.1: bake quality-gate hard rules into the system prompt so they're
    # enforced during generation, not (only) caught after. Saves the $0.10 retry cost.
    forbidden_competitor_domains = ", ".join(sorted(
        list(__import__("config_loader").forbidden_outbound_domains())[:10]
    )) + ", …"
    publish_rules = f"""

PUBLISH RULES (HARD — articles violating these get blocked and discarded):
1. PRICING — The ONLY Velluto price you may quote is "{primary_price_str}" (USD for the EN-primary US article).
   - Do NOT write "€ 149", "149 EUR", "230 EUR", or any other currency/amount as Velluto's price.
   - When discussing the cycling-sunglasses MARKET, use RANGES, not specific competitor prices.
     ✓ "Premium cycling sunglasses range from $150 to $350"
     ✗ "Oakley Sutro costs $280, Rudy Project costs $230"
   - Mention "{primary_price_str}" at most ONCE, near a CTA/product card. Not in body copy.
2. NO OUTBOUND COMPETITOR LINKS — Never use <a href="..."> to link to: {forbidden_competitor_domains}
   Competitor brand names may appear as plain text only.
3. HOMEPAGE LINK — Include exactly one <a href="https://velluto-shop.com">…</a> link with descriptive
   anchor text (e.g., "Velluto", "Velluto cycling eyewear", "premium Velluto glasses").
4. INTERNAL LINKS — At least 3 <a> elements pointing to velluto-shop.com paths total.
5. PRIMARY KEYWORD — The exact primary keyword (or its tokens) MUST appear in <title>, the <h1>, and at least one <h2>.
"""

    system = f"""You are the lead SEO editor and copywriter for Velluto (velluto-shop.com), \
a premium road cycling eyewear brand with Italian design, sold across Europe.

{BRAND_FACTS}

{COPY_PRINCIPLES}
{(chr(10) + seo_ctx + chr(10)) if seo_ctx else ""}
WRITING RULES:
1. Write exclusively in English. Brand names (Velluto, StradaPro, VellutoPuro, VellutoVisione) are unchanged.
2. No <img> tags in flowing text — the cover image is set separately. \
   Product images ONLY in .product-media divs using the APPROVED CDN URLs.
3. Use ONLY the provided product URLs — do not invent URLs.
4. Velluto does NOT offer photochromic, polarized, or prescription lenses.
   You MAY discuss these features when comparing to competitors OR in informational/FAQ sections.
   You MUST NOT attribute them to Velluto products.
   ✓ "Oakley's Prizm lenses are polarized; Velluto's interchangeable system gives you the same control without the lock-in to one tint."
   ✗ "The Velluto Strada Pro's polarized lenses cut glare..."
5. The result should feel like advice from a faster, more experienced cycling friend — not a sales pitch.
6. Use the exact CSS class names from the template (hero, article, .toc, .faq, etc.).
7. EVERY <img> MUST have descriptive alt text (product name + colour + context). NEVER output alt="" or alt="...". This is an accessibility + SEO requirement.
8. NEVER use the em-dash "—" or a spaced en-dash " – " anywhere (body, headings, captions, FAQ). Use commas, periods, colons or parentheses instead. Normal hyphens in compound words (anti-fog, UV400) are fine.
{publish_rules}"""

    # Phase 4: weave the master brief into the prompt when provided
    brief_block = ""
    if brief:
        must_answer = brief.get("must_answer_questions") or []
        do_not_claim = brief.get("do_not_claim") or []
        velluto_angle = (brief.get("velluto_position") or {}).get("main_angle", "")
        supporting   = (brief.get("velluto_position") or {}).get("supporting_angles", [])
        reader       = brief.get("target_reader", "")
        problem      = brief.get("reader_problem", "")
        sections_hint = brief.get("required_sections", [])

        brief_block = (
            "\n=== MASTER BRIEF (must follow) ===\n"
            + (f"Target reader: {reader}\n" if reader else "")
            + (f"Reader problem: {problem}\n" if problem else "")
            + (f"Velluto angle (main): {velluto_angle}\n" if velluto_angle else "")
            + (f"Supporting angles: {' | '.join(supporting)}\n" if supporting else "")
            + (f"Required sections (use as H2 outline): {' | '.join(sections_hint)}\n"
                if sections_hint else "")
            + (f"\nMust-answer questions (use the exact phrasing as H2, then directly "
               f"answer in the first sentence in 40-70 words):\n  - "
               + "\n  - ".join(must_answer) + "\n" if must_answer else "")
            + (f"\nClaims to avoid in this article:\n  - "
               + "\n  - ".join(do_not_claim) + "\n" if do_not_claim else "")
            + "=== END BRIEF ===\n\n"
        )

    # Phase 4.1: prepend gate-fail feedback so the retry attempt knows what to fix
    retry_block = ""
    if retry_feedback:
        retry_block = (
            "\n=== PREVIOUS ATTEMPT FAILED THE QUALITY GATE ===\n"
            "Fix EVERY one of these issues in this regeneration:\n"
            f"{retry_feedback}\n"
            "=== END FAILURES ===\n\n"
        )

    user = f"""Date: {datetime.date.today().strftime('%B %d, %Y')} | Season: {season} | Cycling context: {cycling_ctx}
Primary Keyword (EN): {keyword}
DE Keyword (for context): {keyword_de}
Content angle: {angle if angle else title_hint}
Article number: {art_num}
Quality level {quality['day']} — target: {word_count} words, {faq_count} FAQ questions
{retry_block}{brief_block}
{cdn_images_hint}
PRODUCTS (use only these exact URLs):
{product_json}

Write a complete English magazine article in the Velluto HTML template format.

REQUIRED STRUCTURE for ===BODY=== (article content only — Hero, Author, Ride and Related are rendered by the Shopify Liquid template):

<p class="lede">[Strong opening — a concrete scene from road cycling life, 2-3 sentences]</p>
<p>[Body paragraphs]</p>

[Per section:
<h2 id="sN"><span class="sec-num">0N · Topic area</span>[Section title with optional <em>italics</em>]</h2>
<p>...</p>]

[Include at least one of:
- <div class="spec-strip">...</div> with <span data-count="N"> for animated numbers (25g, UV400, 30 days, etc.)
- <div class="criteria">...</div> with 2x2 .crit tiles for selection criteria
- <div class="pullquote"><q>Quote</q><cite>Source</cite></div>
- <figure class="inline-figure"><img src="[CDN URL]" alt="[REQUIRED descriptive alt — describe the scene + glasses, e.g. 'Road cyclist wearing Velluto StradaPro glasses on a mountain descent'. Never leave blank or '...']"><div class="cap"><span>FIG. 0N: Label</span><span>Caption</span></div></figure>]

[Product card — use EXACTLY this structure:
<div class="product">
  <div class="product-media">
    <span class="product-tag">Editor's Pick</span>
    <img src="[APPROVED CDN URL]" alt="[REQUIRED descriptive alt — product name + colour + context, e.g. 'Velluto StradaPro cycling glasses in Nero with high-contrast lens']">
  </div>
  <div class="product-info">
    <div class="product-eyebrow">Road Cycling Glasses · Road &amp; Gravel</div>
    <h3 class="product-name">Velluto StradaPro<br>Glasses <em>— [Colour]</em></h3>
    <dl class="product-specs">
      <div class="spec"><dt>Weight</dt><dd>25 g</dd></div>
      <div class="spec"><dt>Protection</dt><dd>UV400</dd></div>
      <div class="spec"><dt>Nose pad</dt><dd>Adjustable</dd></div>
      <div class="spec"><dt>Lenses</dt><dd>Interchangeable</dd></div>
    </dl>
    <div class="product-price">{primary_price_str} <small>· Free shipping</small></div>
    <div class="product-cta-row">
      <a class="product-cta" href="[PRODUCT URL]">Buy now <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 7h10M8 3l4 4-4 4"/></svg></a>
      <a class="product-cta secondary" href="[PRODUCT URL]">Details</a>
    </div>
  </div>
</div>]

[Colour variants strip:
<div class="variants">
  [4x <a href="[PRODUCT URL]"><img src="[CDN URL]" alt="[REQUIRED: 'Velluto StradaPro cycling glasses in [Colour]' — never blank or '...']"><div class="v-info"><span class="v-name">[Colour]</span><span class="v-price">{primary_price_str}</span></div></a>]
</div>]

[REQUIRED: FAQ as the last section:
<h2 id="sfaq"><span class="sec-num">0{faq_count} · FAQ</span>Frequently Asked Questions</h2>
<div class="faq">
  [Exactly {faq_count} <details> elements:
  <details open>
    <summary>[Question 1?]</summary>
    <div class="answer">[Answer 1]</div>
  </details>]
</div>]

<p>[Closing CTA → <a class="inline" href="https://velluto-shop.com">velluto-shop.com</a>]</p>

IMPORTANT: No <h1>, no Hero, no Sidebar, no Ride section — the Shopify template renders these automatically.

Use EXACTLY this output format — delimiters on their own lines, no extra text outside them:

===META===
title: <max 65 chars, 100% English, contains the keyword "{keyword}">
meta_description: <max 155 chars, English, contains keyword>
keyword_de: {keyword_de}
keyword_nl: {keyword_nl}
keyword_en: {keyword}
tags: cycling glasses,road cycling,velluto,StradaPro,{keyword}
eyebrow: <topic area label>
category: <category>
hero_sub: <subtitle>
read_time: <number>
===FAQ_JSON===
[
  {{"question": "Question 1?", "answer": "Answer 1."}},
  {{"question": "Question 2?", "answer": "Answer 2."}}
]
===BODY===
[Article content only: lede paragraph, h2 sections, components (spec-strip, criteria, pullquote, product, variants, faq)]
===END===

QUALITY STANDARD: {word_count} words, {faq_count} FAQ questions, at least 2 internal links to product pages."""

    GENERATE_MODEL = "claude-sonnet-4-6"
    response = client.messages.create(
        model=GENERATE_MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}]
    )
    cost = log_usage(response.usage.input_tokens, response.usage.output_tokens, model=GENERATE_MODEL)
    print(f"   Tokens in:{response.usage.input_tokens} out:{response.usage.output_tokens} | ${cost:.4f}")

    raw = response.content[0].text
    return _parse_primary_response(raw, kw)


def _strip_md_fence(html: str) -> str:
    """
    Remove a leading ```html / ``` and trailing ``` markdown fence that Sonnet
    sometimes wraps the ===BODY=== output in. Leaving it in publishes the literal
    text '```html' at the top of the article (and propagates into T&A translations).
    """
    s = (html or "").strip()
    s = re.sub(r'^```[a-zA-Z0-9]*\s*\n?', '', s)   # leading fence (optional lang tag)
    s = re.sub(r'\n?```\s*$', '', s)               # trailing fence
    return s.strip()


def _parse_primary_response(raw: str, kw: dict) -> dict:
    """Parse primary (EN) article response with delimiters ===META===, ===FAQ_JSON===, ===BODY===, ===END===."""
    def extract(tag_start, tag_end):
        m = re.search(rf'{re.escape(tag_start)}\n(.*?)\n{re.escape(tag_end)}', raw, re.DOTALL)
        return m.group(1).strip() if m else ""

    meta_block = extract("===META===",     "===FAQ_JSON===")
    faq_raw    = extract("===FAQ_JSON===", "===BODY===")
    body_html  = _strip_md_fence(extract("===BODY===", "===END==="))

    post: dict = {"keyword": kw.get("keyword", ""), "body_html": body_html}

    for line in meta_block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            post[k.strip()] = v.strip()

    # Build FAQPage JSON-LD
    try:
        faq_items = json.loads(faq_raw)
    except Exception:
        faq_items = []

    if faq_items:
        main_entity = []
        for item in faq_items:
            q = item.get("question", "").strip()
            a = item.get("answer", "").strip()
            if q and a:
                a_clean = re.sub(r'<[^>]+>', '', a)
                main_entity.append({
                    "@type": "Question",
                    "name": q,
                    "acceptedAnswer": {"@type": "Answer", "text": a_clean[:500]}
                })
        if main_entity:
            post["faq_schema"] = json.dumps({
                "@context": "https://schema.org",
                "@type":    "FAQPage",
                "mainEntity": main_entity
            }, ensure_ascii=False, indent=2)
        else:
            post["faq_schema"] = ""
    else:
        post["faq_schema"] = ""

    required = {"title", "meta_description", "tags", "body_html"}
    missing  = required - set(post.keys())
    if missing or not post.get("body_html"):
        raise ValueError(f"Primary response missing fields: {missing}. Raw snippet: {raw[:300]}")
    return post


def build_body_html(post: dict, cover_url: str) -> str:
    """Inject CSS, replace COVER_URL placeholder, append FAQ schema + JS."""
    body = post["body_html"]
    # Replace cover placeholder
    body = body.replace("COVER_URL", cover_url)
    # Append FAQ schema if present
    if post.get("faq_schema"):
        body += f'\n<script type="application/ld+json">\n{post["faq_schema"]}\n</script>\n'
    # Phase 6 (Point 4 / GEO): Article JSON-LD — helps rich results AND makes the
    # piece easier for AI engines (ChatGPT/Perplexity/AI Overviews) to attribute & cite.
    try:
        headline = (post.get("title") or post.get("keyword") or "").strip()[:110]
        if headline:
            article_schema = {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": headline,
                "image": cover_url or "",
                "author":    {"@type": "Organization", "name": "Velluto"},
                "publisher": {
                    "@type": "Organization", "name": "Velluto",
                    "logo": {"@type": "ImageObject",
                              "url": "https://velluto-shop.com/cdn/shop/files/velluto-logo.png"},
                },
                "datePublished": datetime.date.today().isoformat(),
                "dateModified":  datetime.date.today().isoformat(),
            }
            if post.get("meta_description"):
                article_schema["description"] = post["meta_description"][:300]
            body += ('\n<script type="application/ld+json">\n'
                     + json.dumps(article_schema, ensure_ascii=False, indent=2)
                     + '\n</script>\n')
    except Exception as _e:
        print(f"   ⚠️  Article schema injection skipped: {_e}")
    # Append JS behaviors
    body += ARTICLE_JS
    font_link = (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">'
    )
    # Inject canonical pointing to the root (non-locale) URL — strips /nl/, /fr/ etc. prefixes
    canonical_js = (
        '<script>'
        '(function(){'
        'var l=document.createElement("link");l.rel="canonical";'
        'l.href="https://velluto-shop.com"+window.location.pathname.replace(/^\\/[a-z]{2}(-[a-z]{2,4})?\\//, "/");'
        'document.head.appendChild(l);'
        '})();'
        '</script>'
    )
    return f"{canonical_js}\n{body}"


def graphql_with_vars(query: str, variables: dict) -> dict:
    """GraphQL call with variables support."""
    r = requests.post(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json",
        headers=SHOPIFY_HEADERS,
        json={"query": query, "variables": variables},
        timeout=20,
    )
    return r.json().get("data", {})


def get_translatable_digests(article_id: int) -> dict:
    """Fetch translatable content digests for a Shopify article."""
    gid = f"gid://shopify/Article/{article_id}"
    query = """
    query($id: ID!) {
      translatableResource(resourceId: $id) {
        translatableContent { key value digest locale }
      }
    }
    """
    data = graphql_with_vars(query, {"id": gid})
    items = (data.get("translatableResource") or {}).get("translatableContent", [])
    return {item["key"]: item["digest"] for item in items if item.get("digest")}


@retry(max_attempts=2, delay=5, label="register_translation")
def register_shopify_translation(article_id: int, locale: str, title: str,
                                  body_html: str, meta_desc: str, digests: dict) -> bool:
    """Register NL or EN translation for a published article via Shopify translationsRegister."""
    gid = f"gid://shopify/Article/{article_id}"
    translations = []
    # NOTE: Shopify's translatable SEO-snippet key is `meta_description` (NOT
    # `summary_html`). Registering only summary_html left non-EN markets with the
    # ENGLISH meta description in their SERPs. We now target meta_description
    # (the real SEO key) AND summary_html (blog-listing excerpt) — whichever the
    # article actually exposes (keys without a digest are skipped automatically).
    for key, value in [("title", title), ("body_html", body_html),
                       ("meta_description", meta_desc), ("summary_html", meta_desc)]:
        digest = digests.get(key, "")
        if not digest:
            continue
        translations.append({
            "key": key,
            "value": value,
            "translatableContentDigest": digest,
            "locale": locale,
        })
    if not translations:
        print(f"   ⚠️  No digests found for {locale} — skipping translation registration")
        return False

    mutation = """
    mutation translationsRegister($resourceId: ID!, $translations: [TranslationInput!]!) {
      translationsRegister(resourceId: $resourceId, translations: $translations) {
        userErrors { field message }
        translations { key value locale }
      }
    }
    """
    result = graphql_with_vars(mutation, {"resourceId": gid, "translations": translations})
    errors = (result.get("translationsRegister") or {}).get("userErrors", [])
    if errors:
        # "primary locale" error means this locale IS the shop default — not a real failure
        primary_locale_errors = [e for e in errors if "primary locale" in e.get("message", "").lower()]
        if primary_locale_errors:
            print(f"   ℹ️  [{locale}] is the shop's primary locale — translation skipped (content is the published article)")
            return True  # not a failure
        print(f"   ⚠️  Translation register errors [{locale}]: {errors}")
        return False
    registered = (result.get("translationsRegister") or {}).get("translations", [])
    print(f"   ✅ [{locale}] {len(registered)} translation(s) registered")
    return True


@retry(max_attempts=2, delay=10, label="generate_market_adaptation")
def generate_market_adaptation(de_post: dict, target_locale: str, market: dict,
                               commercial: dict | None = None) -> dict:
    """
    Adapt the primary EN article for a target market locale (DE, NL, FR, etc.).
    Uses Claude Haiku for cost efficiency (~$0.025 vs $0.145 with Sonnet).
    market = {"keyword": "...", "intent": "..."}
    commercial: optional commercial config from load_commercial_config(). When
                provided, Haiku is instructed to replace ALL price strings in
                the body with the target market's current price (e.g. NL = 69 EUR).
    """
    lang_name  = LOCALE_LANG_NAMES.get(target_locale, target_locale)
    cycling_ctx = LOCALE_CYCLING_CONTEXT.get(target_locale, "local cycling culture and routes")
    target_kw  = market.get("keyword", "")
    intent     = market.get("intent", "")

    # Phase 1: per-market price rule. Maps target_locale short ("de", "nl", …)
    # to the right entry in the commercial config and builds the rule string.
    price_rule = ""
    if commercial:
        from commercial_config import for_locale_short as _cc_for_locale
        mcfg = _cc_for_locale(target_locale)
        if mcfg and mcfg.get("current_price"):
            cur, price = mcfg["currency"], mcfg["current_price"]
            price_token = (
                f"{price} EUR" if cur == "EUR" else
                f"${price}"   if cur == "USD" else
                f"{price} {cur}"
            )
            offer_note = " (current test offer — frame as the current price, not as a permanent discount)" \
                         if mcfg.get("offer_status") == "test" else ""
            price_rule = (
                f"8. Pricing for this market: when the article references a Velluto price, use exactly "
                f"'{price_token}'{offer_note}. Replace any other currency or amount you see in the source HTML.\n"
            )

    ADAPT_MODEL = "claude-haiku-4-5-20251001"

    # Body adaptation — Haiku handles HTML structure well
    body_r = client.messages.create(
        model=ADAPT_MODEL,
        max_tokens=12000,
        system=(
            f"You are an SEO copywriter adapting cycling content for the {lang_name}-speaking market. "
            f"Target keyword: '{target_kw}'. Search intent: {intent}\n\n"
            "Rules (follow exactly):\n"
            f"1. Write entirely in {lang_name} — no German words anywhere.\n"
            f"2. Use '{target_kw}' naturally in H1, opening paragraph, and at least one H2.\n"
            "3. Keep ALL HTML tags, class names, IDs and structure IDENTICAL.\n"
            "4. Brand names stay unchanged: Velluto, StradaPro, VellutoPuro, VellutoVisione.\n"
            "5. All URLs (href, src) stay unchanged.\n"
            f"6. Adapt local references to reflect: {cycling_ctx}.\n"
            "7. Output ONLY the adapted HTML body — no markdown fences, no comments outside HTML.\n"
            "8. NEVER introduce the em-dash '—' or a spaced en-dash ' – '. Use commas/periods. (Normal hyphens in words are fine.)\n"
            f"{price_rule}"
        ),
        messages=[{"role": "user", "content": de_post["body_html"]}]
    )
    cost = log_usage(body_r.usage.input_tokens, body_r.usage.output_tokens, model=ADAPT_MODEL)
    print(f"   [{target_locale}] Adaptation tokens in:{body_r.usage.input_tokens} out:{body_r.usage.output_tokens} | ${cost:.4f}")
    adapted_body = _strip_md_fence(body_r.content[0].text)

    # Title + meta in a single Haiku call to save one round-trip
    meta_r = client.messages.create(
        model=ADAPT_MODEL,
        max_tokens=200,
        system="Return ONLY valid JSON, no extra text.",
        messages=[{"role": "user", "content":
            f"Adapt these for the {lang_name} market. Keyword: '{target_kw}'.\n"
            f"EN title: {de_post.get('title', '')}\n"
            f"EN meta: {de_post.get('meta_description', '')}\n\n"
            f"Return: {{\"title\": \"<max 65 chars, written in {lang_name}, contains the keyword>\", "
            f"\"meta\": \"<max 155 chars, written in {lang_name}, contains the keyword>\"}}"
        }]
    )
    log_usage(meta_r.usage.input_tokens, meta_r.usage.output_tokens, model=ADAPT_MODEL)
    raw = meta_r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    try:
        meta_data = json.loads(raw)
        adapted_title = meta_data.get("title", target_kw)[:65]
        adapted_meta  = meta_data.get("meta",  target_kw)[:155]
    except Exception:
        adapted_title = target_kw
        adapted_meta  = target_kw

    # Guard: if the model echoed the ENGLISH title verbatim (a known Haiku slip),
    # fall back to the localized keyword so non-EN markets never show an EN headline.
    en_title = (de_post.get("title", "") or "").strip().lower()
    if en_title and adapted_title.strip().lower() == en_title and target_kw:
        adapted_title = target_kw[:65]

    return {
        "title":     adapted_title,
        "body_html": adapted_body,
        "meta_desc": adapted_meta,
    }


def publish_de_primary(kw: dict, products: list[dict], commercial: dict | None = None,
                       brief: dict | None = None):
    """Orchestrate: generate EN article → publish (EN primary) → register DE/NL/FR/… via T&A.

    commercial: optional commercial config (dict of per-market price/UVP/offer).
                When None, a fresh one is loaded lazily — but the caller should
                pass it in to avoid duplicate Shopify calls.
    brief:      optional Phase 4 master brief. When provided:
                  - generate_de_primary uses brief.must_answer_questions, claims_to_avoid
                  - quality_gate runs after generation and HARD-BLOCKS publish if it fails
                When None, falls back to legacy keyword-only flow.
    """
    from en_keyword_queue import mark_en_keyword_used
    if commercial is None:
        commercial = load_commercial_config()

    keyword = kw["keyword"]
    print(f"\n── Primary Article (EN) ─────────────────────────────")
    print(f"   EN Keyword: {keyword} (vol: {kw.get('volume','?')}, phase: {kw.get('phase','?')})")

    art_num = get_article_number()

    print(f"   Researching market keywords...")
    try:
        mkt_kws = research_market_keywords(keyword)
        def _kw_label(loc):
            entry = mkt_kws[loc]
            vol   = entry.get("volume", 0)
            vol_s = f" ({vol:,}/mo)" if vol else ""
            return f"{loc.upper()}: {entry['keyword']}{vol_s}"
        kw_summary = " | ".join(
            _kw_label(loc)
            for loc in ["de", "nl", "en", "fr", "es", "it"]
            if loc in mkt_kws
        )
        print(f"   {kw_summary}")
        extra = " | ".join(
            _kw_label(loc)
            for loc in ["da", "nb", "pl", "pt-PT", "sv"]
            if loc in mkt_kws
        )
        if extra:
            print(f"   {extra}")
    except Exception as e:
        print(f"   ⚠️  Keyword research failed: {e} — using fallback")
        mkt_kws = {"de": {"keyword": keyword, "intent": "", "volume": 0}}
        for loc in SHOP_LOCALES:
            mkt_kws[loc] = {"keyword": keyword, "intent": "", "volume": 0}

    # EN keyword is the primary keyword; other locales come from market research
    kw_ctx = {**kw, "art_num": art_num,
              "keyword_en": keyword,   # EN queue keyword is always the primary
              "keyword_de": mkt_kws["de"]["keyword"],
              "keyword_nl": mkt_kws.get("nl", {}).get("keyword", keyword)}

    quality = get_quality_targets()
    print(f"   Quality Day {quality['day']} — target: {quality['word_count']} words, {quality['faq_count']} FAQ")

    cover_url = pick_cover(keyword, keyword)

    # Generate EN article — up to 3 attempts; retries inject specific failures as feedback
    from briefs.quality_gate import gate as _quality_gate
    post = generate_de_primary(kw_ctx, products, quality, commercial=commercial, brief=brief)
    qa = None
    for attempt in range(3):
        # ── 1. Brand FACT check (legacy) ──────────────────────────────────
        issues = [i for pat, msg in FORBIDDEN_CLAIMS
                  for i in ([f"[FACT] {msg}"] if re.search(pat, post.get("body_html",""), re.IGNORECASE) else [])]
        if not post.get("body_html"):
            issues.append("[FACT] Missing body_html")
        fact_issues = [i for i in issues if i.startswith("[FACT]")]
        if fact_issues:
            if attempt < 2:
                print(f"   ✗ Brand fact violation (attempt {attempt+1}/3) — regenerating: {fact_issues[0]}")
                post = generate_de_primary(kw_ctx, products, quality, commercial=commercial, brief=brief,
                                            retry_feedback="\n".join(f"- {i}" for i in fact_issues))
                continue
            else:
                raise RuntimeError(f"Brand fact violation after 3 attempts: {fact_issues}")
        # ── 2. Phase 4 Quality Gate (price / keyword / links / PAA / etc.) ─
        qa = _quality_gate(post, brief, market_code="US", commercial=commercial)
        if qa["auto_fixes"]:
            for af in qa["auto_fixes"]:
                print(f"   🛠  QA auto-fix: {af}")
        if not qa["passed"]:
            if attempt < 2:
                print(f"   ✗ Quality gate FAILED (attempt {attempt+1}/3) — regenerating with feedback:")
                for issue in qa["hard_issues"]:
                    print(f"      {issue}")
                post = generate_de_primary(kw_ctx, products, quality, commercial=commercial, brief=brief,
                                            retry_feedback="\n".join(f"- {i}" for i in qa["hard_issues"]))
                continue
            else:
                print(f"   ❌ Quality gate FAILED after 3 attempts — publish blocked.")
                for issue in qa["hard_issues"]:
                    print(f"      {issue}")
                print(f"   (logged to output/quality_gate_failures.json)")
                return  # Hard-stop: no publish, no T&A
        # All checks passed
        if not issues:
            print(f"   ✅ EN quality check passed (attempt {attempt+1}, gate auto_fixes={len(qa['auto_fixes'])})")
        else:
            for iss in issues:
                print(f"   ⚠️  {iss}")
        break

    # Guard: check if an article with this title's handle already exists (prevents -1 duplicates)
    expected_slug = re.sub(r'[^a-z0-9]+', '-', post.get("title", "").lower()).strip('-')
    if expected_slug:
        existing_check = requests.get(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json",
            params={"handle": expected_slug, "fields": "id,handle"},
            headers=SHOPIFY_HEADERS, timeout=15,
        ).json().get("articles", [])
        if existing_check:
            print(f"   ⚠️  Article handle '{expected_slug}' already exists (ID:{existing_check[0]['id']}) — skipping publish")
            mark_en_keyword_used(keyword)
            return

    # Phase 4.1: quality gate already ran inside the retry loop above.
    # If we reach here, post passed both FACT and gate checks.
    body_html = build_body_html(post, cover_url)
    aid, handle = publish(
        title=post["title"],
        body_html=body_html,
        meta_desc=post.get("meta_description", "")[:155],
        tags=post.get("tags", f"cycling glasses,road cycling,velluto,{keyword}"),
        featured_url=cover_url,
    )

    mark_en_keyword_used(keyword)
    increment_quality_day()

    # Register market adaptations
    print(f"   Fetching translatable digests for article {aid}...")
    try:
        digests = get_translatable_digests(aid)
        print(f"   Got {len(digests)} digests: {list(digests.keys())}")
    except Exception as e:
        print(f"   ⚠️  Could not fetch digests: {e}")
        digests = {}

    for locale in SHOP_LOCALES:
        market = mkt_kws.get(locale, {"keyword": keyword, "intent": ""})
        print(f"   Generating {locale.upper()} adaptation (kw: {market['keyword']})...")
        try:
            adaptation = generate_market_adaptation(post, locale, market, commercial=commercial)
            ok = register_shopify_translation(
                aid, locale,
                adaptation["title"],
                adaptation["body_html"],
                adaptation["meta_desc"],
                digests,
            )
            status = "registered" if ok else "failed"
            print(f"   [{locale}] Adaptation {status}: {adaptation['title']}")
        except Exception as e:
            print(f"   ❌ [{locale}] Adaptation error: {e}")

    blog_handle = "velluto-the-magazine"
    published = json.load(open(PUBLISHED_LOG)) if os.path.exists(PUBLISHED_LOG) else []
    published.append({
        "title":    post["title"],
        "url":      f"https://velluto-shop.com/blogs/{blog_handle}/{handle}",
        "topic":    keyword,
        "keyword":  keyword,
        "lang":     "en",
        "phase":    kw.get("phase"),
        "tags":     post.get("tags", ""),
        "translations": {loc: mkt_kws.get(loc, {}) for loc in SHOP_LOCALES},
    })
    json.dump(published, open(PUBLISHED_LOG, "w"), indent=2)
    print(f"   EN published: {post['title']}")
    print(f"   https://velluto-shop.com/blogs/{blog_handle}/{handle}")


# ── Main ─────────────────────────────────────────────────────────────────────

def publish_one(topic: str, trends: str, products: list[dict], post_num: int):
    print(f"\n── Post {post_num}/3 ─────────────────────────────")
    print(f"📝 Topic: {topic}")
    cover_url = pick_cover(topic, topic)

    post = generate(topic, trends, cover_url, products)

    for attempt in range(2):
        issues   = validate(post, products)
        fact_issues  = [i for i in issues if i.startswith("[FACT]")]
        other_issues = [i for i in issues if not i.startswith("[FACT]")]
        if fact_issues and attempt == 0:
            print(f"   ✗ Brand fact violation — regenerating")
            post = generate(topic, trends, cover_url, products)
            continue
        if other_issues:
            for iss in other_issues: print(f"   ⚠️  {iss}")
        else:
            print("   ✅ Quality check passed")
        break

    # Publish EN as primary; no tab switcher — T&A handles other locales
    aid, handle = publish(
        title=post["title_en"],
        body_html=post["en_html"],
        meta_desc=post["meta_description"],
        tags=post["tags"],
        featured_url=cover_url
    )
    # Register NL and DE translations via Shopify T&A
    try:
        digests = get_translatable_digests(aid)
        for locale, html_key in [("nl", "nl_html"), ("de", "de_html")]:
            adapted = post.get(html_key, "")
            if adapted:
                register_shopify_translation(
                    article_id=aid, locale=locale,
                    title=post["title_en"],  # fallback: same title
                    body_html=adapted,
                    meta_desc=post.get("meta_description", ""),
                    digests=digests,
                )
    except Exception as e:
        print(f"   ⚠️  Fallback T&A registration failed: {e}")
    # Record for link_builder.py
    published = json.load(open(PUBLISHED_LOG)) if os.path.exists(PUBLISHED_LOG) else []
    published.append({
        "title":   post["title_en"],
        "url":     f"https://velluto-shop.com/blogs/velluto-the-magazine/{handle}",
        "topic":   topic,
        "keyword": post.get("keyword", ""),
        "tags":    post.get("tags", ""),
    })
    json.dump(published, open(PUBLISHED_LOG, "w"), indent=2)


def main():
    print(f"\n🚴 Velluto SEO Bot — {datetime.date.today()} (EN-primary, quality-compounding, multilingual via Shopify Translate & Adapt)")
    print("=" * 55)

    json.dump([], open(PUBLISHED_LOG, "w"))  # reset daily publish log

    # Phase 1: load commercial config (price/UVP/offer per market) ONCE per run.
    # Threaded into generate_de_primary + generate_market_adaptation so prices
    # are never hard-coded. NL currently runs a 69 EUR test offer.
    print("💶 Loading commercial config (per-market pricing)...")
    commercial = load_commercial_config()
    test_markets = [m for m, c in commercial.items() if c.get("offer_status") == "test"]
    print(f"   {len(commercial)} markets loaded"
          + (f" | test-offer markets: {', '.join(test_markets)}" if test_markets else ""))

    # Phase 2: research bundle (competitor sitemaps + SERP + PAA + AIO + GSC).
    # Best-effort — any failure here logs a warning but never blocks publishing.
    # Outputs land in data/processed/*.json for Phase 3+ to consume.
    research = {}
    try:
        print("🔬 Running research bundle (competitors + SERP + PAA + AIO + GSC)...")
        from research.runner import run_research_bundle
        research = run_research_bundle()
        print(f"   {research.get('summary_line', '(no summary)')}")
    except Exception as e:
        print(f"   ⚠️  Research bundle failed: {e} — continuing without it")

    # Phase 5: performance loop — turn GSC per-page deltas into a feedback file
    # the scorer consumes (scale winners / refresh decayers), and write the
    # Claude-readable 28-day audit when due. Best-effort: never blocks publishing.
    try:
        print("📈 Performance loop (GSC + Shopify revenue → decisions)...")
        from performance import classifier as _perf_classifier
        from performance import audit as _perf_audit
        from performance import conversions as _perf_conv
        _perf_conv.run()                            # → data/processed/conversion_performance.json (Phase 6)
        _perf_classifier.run()                      # → data/processed/performance_feedback.json
        _audit = _perf_audit.maybe_run()            # 28-day-gated report
        if _audit.get("ran"):
            print(f"   ✓ 28-day performance audit: {_audit['path']}")
        else:
            print(f"   · audit {_audit.get('reason', 'skipped')}")
    except Exception as e:
        print(f"   ⚠️  Performance loop failed: {e} — continuing")

    print("🛍️  Fetching active products...")
    products = get_products()
    print(f"   {len(products)} active products")

    # Phase 3: strategic decision layer — pick ONE of 10 actions for today.
    # Gates publishing on opportunity score. Falls back to EN keyword queue
    # if decision layer fails OR returns an action not yet implemented.
    decision = None
    decision_keyword = None
    try:
        print("\n🧠 Building content inventory + scoring opportunities...")
        from decision.content_inventory  import build as build_inventory
        from decision.opportunity_scorer import score as score_opportunities
        from decision.topic_selector     import choose as choose_topic
        from decision.topic_selector     import write_daily_research_report

        inventory = build_inventory()
        scored    = score_opportunities(research, inventory)
        decision  = choose_topic(scored, research, inventory)
        write_daily_research_report(decision, scored, research)
        print(f"   ✓ Decision: {decision['chosen_action']} "
              f"(topic='{decision.get('chosen_topic')}', score={decision.get('opportunity_score')})")
        if decision.get("why_this_topic"):
            print(f"     Why: {decision['why_this_topic']}")
    except Exception as e:
        print(f"   ⚠️  Decision layer failed: {e} — falling back to EN keyword queue")
        import traceback; traceback.print_exc()
        decision = None

    published = 0

    # ── Phase 3 action handlers ────────────────────────────────────────────
    if decision and decision.get("chosen_action") == "monitor_only":
        print("\n📊 Monitor-only day: no publish, no update. Strategic decision logged.")
        # Skip publish; still let downstream optimizer scripts run via run.sh.

    elif decision and decision.get("chosen_action") == "create_new_article":
        kw_decision = {
            "keyword":   decision["chosen_keyword"],
            "keyword_en": decision["chosen_keyword"],
            "phase":     "decision",
            "angle":     decision.get("required_content_type", "buying_guide"),
            "art_num":   None,  # generated inside publish_de_primary
        }

        # Phase 4: build US master brief + localization briefs
        master_brief = None
        try:
            from briefs.us_master_brief    import build_brief
            from briefs.localization_brief import build_all_localization_briefs
            print(f"\n── Building US master brief + localization briefs ──")
            master_brief = build_brief(decision, research, inventory)
            build_all_localization_briefs(master_brief, research, commercial)
        except Exception as e:
            print(f"   ⚠️  Brief building failed: {e} — falling back to brief-less generation")
            import traceback; traceback.print_exc()
            master_brief = None  # Safe fallback: existing path

        try:
            print(f"\n── Publishing decision-driven article ──")
            publish_de_primary(kw_decision, products, commercial=commercial, brief=master_brief)
            published += 1
        except Exception as e:
            print(f"   ❌ Decision-driven publish failed: {e}")
            import traceback; traceback.print_exc()

        # Phase 6 — throughput: on a STRONG signal (high-scoring commercial /
        # revenue-winner candidates), publish up to a couple more articles the same
        # day. Opted in by the operator. Fully guarded; extra cost only on strong days.
        STRONG_SIGNAL_SCORE = 85
        MAX_EXTRA_ACTIONS    = 2
        try:
            extra_done = 0
            primary_kw = decision.get("chosen_keyword")
            cand_list  = scored.get("candidates", []) if isinstance(scored, dict) else []
            for cand in cand_list:
                if extra_done >= MAX_EXTRA_ACTIONS:
                    break
                if cand.get("recommended_action") != "create_new_article":
                    continue
                if cand.get("keyword") == primary_kw:
                    continue
                strong = (cand.get("opportunity_score", 0) >= STRONG_SIGNAL_SCORE
                          and (cand.get("commercial_comparison")
                               or cand.get("performance_tier") in ("revenue_winner", "winner")))
                if not strong:
                    continue
                angle = "comparison" if cand.get("commercial_comparison") else "buying_guide"
                extra_kw = {"keyword": cand["keyword"], "keyword_en": cand["keyword"],
                            "phase": "decision-extra", "angle": angle, "art_num": None}
                try:
                    print(f"\n── Strong signal: extra article '{cand['keyword']}' "
                          f"(score {cand.get('opportunity_score')}, tier "
                          f"{cand.get('performance_tier','-')}) ──")
                    eb = None
                    try:
                        from briefs.us_master_brief    import build_brief as _bb
                        from briefs.localization_brief import build_all_localization_briefs as _bl
                        edec = {**decision, "chosen_keyword": cand["keyword"],
                                "chosen_topic": cand["keyword"],
                                "required_content_type": angle}
                        eb = _bb(edec, research, inventory)
                        _bl(eb, research, commercial)
                    except Exception as _be:
                        print(f"   ⚠️  Extra brief failed: {_be} — brief-less")
                        eb = None
                    publish_de_primary(extra_kw, products, commercial=commercial, brief=eb)
                    published += 1
                    extra_done += 1
                except Exception as _ee:
                    print(f"   ⚠️  Extra publish failed: {_ee}")
            if extra_done:
                print(f"   ✓ Throughput: +{extra_done} extra strong-signal article(s) today")
        except Exception as _e:
            print(f"   ⚠️  Throughput step skipped: {_e}")

    elif decision and decision.get("chosen_action") in (
            "update_existing_article", "improve_paa_blocks", "improve_ai_overview_blocks",
            "improve_product_page", "improve_collection_page", "add_internal_links",
            "rewrite_metadata", "create_localization_briefs"):
        print(f"\n⏸  Action '{decision['chosen_action']}' not yet implemented (Phase 4+). "
              f"Logging decision, skipping publish today.")

    # ── Fallback: EN keyword queue (used when decision layer failed/None) ──
    if published == 0 and (decision is None
                            or decision.get("chosen_action") not in (
                                "monitor_only",
                                "update_existing_article", "improve_paa_blocks",
                                "improve_ai_overview_blocks", "improve_product_page",
                                "improve_collection_page", "add_internal_links",
                                "rewrite_metadata", "create_localization_briefs")):
        try:
            from en_keyword_queue import get_next_en_keyword, get_en_queue_status
            kw = get_next_en_keyword()
            if kw:
                status = get_en_queue_status()
                by_p  = status.get("by_phase", {})
                remaining = status["total"] - status["used"]
                print(f"\n── Fallback: EN keyword queue ({remaining} remaining "
                      f"P1:{by_p.get('1',{}).get('total',0)-by_p.get('1',{}).get('done',0)} "
                      f"P2:{by_p.get('2',{}).get('total',0)-by_p.get('2',{}).get('done',0)} "
                      f"P3:{by_p.get('3',{}).get('total',0)-by_p.get('3',{}).get('done',0)})")
                publish_de_primary(kw, products, commercial=commercial)
                published += 1
            else:
                print("   ⚠️  EN keyword queue exhausted — falling back to multi-lang post")
        except Exception as e:
            print(f"   ❌ EN primary post failed: {e}")
            import traceback; traceback.print_exc()

    # ── Fallback: classic multi-language post ────────────────────────────────
    if published == 0:
        print("\n📡 Searching trends + researching new topics (fallback mode)...")
        trends = search_trends()
        try:
            research_new_topics()
        except Exception as e:
            print(f"   ⚠️  Topic research skipped: {e}")
        try:
            topic = get_unused_topic()
            publish_one(topic, trends, products, 1)
            published += 1
        except Exception as e:
            print(f"   ❌ Fallback post failed: {e}")

    print_usage()
    print(f"\n✅ {published}/1 post published today.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        tb = traceback.format_exc().splitlines()
        # Keep last 5 lines of traceback for context
        tb_short = " | ".join(tb[-5:]).strip()
        msg = (f"❌ Velluto SEO Bot FAILED {datetime.date.today()}\n"
               f"{type(e).__name__}: {str(e)[:180]}\n"
               f"Logs: https://github.com/leopold-cell/velluto-seo-bot/actions")
        print(f"\n{msg}\n{tb_short}")
        notify(msg)
        raise
