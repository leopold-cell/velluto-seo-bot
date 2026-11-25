"""
AI-content label for every blog article the bot publishes.

The operator asked (2026-11-25) that all AI-generated content be marked at the bottom
of the page. One short notice is appended to the end of each article body, in the
article's own language, and re-added in the native text after translation so the
translation model cannot reword or drop it. The wording claims only what is true:
the text and images were created wholly or partly with AI, and translations are
machine translations. It makes NO claim of human review.

add_notice() is idempotent: it replaces an existing notice and never doubles it.
"""
import json
import os
import re

MARK = "velluto-ai-notice"

_TEXT = {
    "en": "Note: This article and its images were created wholly or partly with artificial "
          "intelligence. Translations are machine-generated. Check product details and prices "
          "on the product page.",
    "de": "Hinweis: Dieser Beitrag und seine Bilder wurden ganz oder teilweise mit künstlicher "
          "Intelligenz erstellt. Übersetzungen sind maschinell erstellt. Produktangaben und "
          "Preise bitte auf der Produktseite prüfen.",
    "nl": "Let op: Dit artikel en de afbeeldingen zijn geheel of gedeeltelijk met kunstmatige "
          "intelligentie gemaakt. Vertalingen zijn machinaal. Controleer productgegevens en "
          "prijzen op de productpagina.",
    "fr": "Remarque : cet article et ses images ont été créés en tout ou en partie avec "
          "l'intelligence artificielle. Les traductions sont automatiques. Vérifiez les "
          "caractéristiques et les prix sur la page produit.",
    "es": "Aviso: este artículo y sus imágenes se han creado total o parcialmente con "
          "inteligencia artificial. Las traducciones son automáticas. Comprueba los datos y "
          "precios del producto en su página.",
    "it": "Nota: questo articolo e le sue immagini sono stati creati in tutto o in parte con "
          "l'intelligenza artificiale. Le traduzioni sono automatiche. Controlla dati e prezzi "
          "dei prodotti sulla pagina del prodotto.",
    "da": "Bemærk: Denne artikel og dens billeder er helt eller delvist skabt med kunstig "
          "intelligens. Oversættelser er maskinelle. Tjek produktoplysninger og priser på "
          "produktsiden.",
    "nb": "Merk: Denne artikkelen og bildene er helt eller delvis laget med kunstig "
          "intelligens. Oversettelser er maskinelle. Sjekk produktopplysninger og priser på "
          "produktsiden.",
    "pl": "Uwaga: ten artykuł i jego obrazy zostały w całości lub częściowo stworzone przy "
          "użyciu sztucznej inteligencji. Tłumaczenia są maszynowe. Dane i ceny produktów "
          "sprawdź na stronie produktu.",
    "pt-PT": "Aviso: este artigo e as suas imagens foram criados total ou parcialmente com "
             "inteligência artificial. As traduções são automáticas. Confirme os dados e os "
             "preços do produto na página do produto.",
    "sv": "Observera: Den här artikeln och dess bilder har helt eller delvis skapats med "
          "artificiell intelligens. Översättningar är maskinella. Kontrollera produktuppgifter "
          "och priser på produktsidan.",
}

_EXISTING = re.compile(
    r'\s*<(?P<t>p|div)\b[^>]*\b' + MARK + r'\b[^>]*>.*?</(?P=t)>\s*', re.S | re.I)

# Topics of public interest (health, consumer safety) where Art. 50(4) AI Act may require
# the label for AI text: the notice goes to the TOP of the article there, not the end.
_TOPIC_TOKENS = {"uv", "uv400", "protection", "protect", "safety", "burning", "blurry"}


def is_public_interest_topic(handle_or_title: str) -> bool:
    toks = set(re.split(r"[^a-z0-9]+", (handle_or_title or "").lower()))
    return bool(toks & _TOPIC_TOKENS)


def notice_html(lang: str) -> str:
    text = _TEXT.get(lang) or _TEXT["en"]
    return (f'<p class="{MARK}" style="margin:0 0 2em;padding:.8em 1em;border:1px solid #ddd;'
            f'font-size:.85em;opacity:.85">{text}</p>')


def add_notice(body: str, lang: str = "en", top: bool = False) -> str:
    """Put the label at the end (default) or the very top of the body, replacing any
    earlier one so it never doubles."""
    clean = _EXISTING.sub("", body or "").strip()
    if top:
        return notice_html(lang) + "\n\n" + clean + "\n"
    return clean + "\n\n" + notice_html(lang) + "\n"


def has_notice(body: str) -> bool:
    return MARK in (body or "")


def notice_placed(body: str, lang: str, top: bool) -> bool:
    """True when the current-wording notice sits where it belongs."""
    b = (body or "").strip()
    n = notice_html(lang)
    return b.startswith(n) if top else (b.endswith(n) and not b.startswith(n))


# ── AI-generated images: a label right at the image ────────────────────────────
IMG_MARK = "velluto-ai-image-label"
_IMG_TEXT = {
    "en": "AI-generated image", "de": "KI-generiertes Bild", "nl": "AI-gegenereerde afbeelding",
    "fr": "Image générée par IA", "es": "Imagen generada con IA", "it": "Immagine generata con IA",
    "da": "AI-genereret billede", "nb": "KI-generert bilde", "pl": "Obraz wygenerowany przez AI",
    "pt-PT": "Imagem gerada por IA", "sv": "AI-genererad bild",
}
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.I)
_INVENTORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "ai_media_inventory.json")


def _stem(url: str) -> str:
    return os.path.splitext(os.path.basename(url.split("?")[0]))[0]


def ai_image_stems() -> set:
    """File stems of every image the inventory classifies as AI-generated."""
    try:
        inv = json.load(open(_INVENTORY, encoding="utf-8"))
    except Exception:
        return set()
    return {_stem(v["url"]) for v in inv.values()
            if isinstance(v, dict) and v.get("verdict") == "ai" and v.get("url")}


def label_ai_images(body: str, lang: str = "en", stems: set | None = None) -> str:
    """Add a visible 'AI-generated image' line directly behind each AI image. Idempotent."""
    stems = ai_image_stems() if stems is None else stems
    if not stems or not body:
        return body
    text = _IMG_TEXT.get(lang) or _IMG_TEXT["en"]
    label = (f'<span class="{IMG_MARK}" style="display:block;font-size:.8em;opacity:.8;'
             f'padding:.3em .6em">{text}</span>')
    out, pos = [], 0
    for m in _IMG_TAG.finditer(body):
        out.append(body[pos:m.end()])
        pos = m.end()
        src = _SRC.search(m.group(0))
        if src and _stem(src.group(1)) in stems and IMG_MARK not in body[pos:pos + 250]:
            out.append(label)
    out.append(body[pos:])
    return "".join(out)
