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


def notice_html(lang: str) -> str:
    text = _TEXT.get(lang) or _TEXT["en"]
    return (f'<p class="{MARK}" style="margin-top:2.5em;padding-top:1em;'
            f'border-top:1px solid #ddd;font-size:.85em;opacity:.75">{text}</p>')


def add_notice(body: str, lang: str = "en") -> str:
    """Append the label at the very end of the visible body, replacing any earlier one."""
    clean = _EXISTING.sub("", body or "")
    return clean.rstrip() + "\n\n" + notice_html(lang) + "\n"


def has_notice(body: str) -> bool:
    return MARK in (body or "")
