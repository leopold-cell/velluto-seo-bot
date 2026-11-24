#!/usr/bin/env python3
"""
Link the Velluto Night Glow LED valve cap lights from the gift articles.

WHY
The operator asked for the Night Glow to appear in the Christmas gift articles for
cyclists. A single hand-written paragraph per language goes into every gift article
(EN body via REST, translations via translationsRegister), placed after the
stocking-stuffer section so it reads as one more small-gift idea.

The paragraph only states facts from BRAND_FACTS (seo_bot.py): decorative, motion
activated, Schrader/Dunlop but NOT Presta, not a replacement for StVZO lighting,
real pack prices. No safety promise.

Idempotent (skips a body that already links the product) and cheap (REST + GraphQL,
no LLM). Dry-run by default; run.sh passes --apply so gift articles written later
get the link too.

Usage:
  python3 scripts/link_night_glow.py            # dry-run
  python3 scripts/link_night_glow.py --apply
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

URL = "https://velluto-shop.com/products/velluto-night-glow-led-valve-caps"
APPLY = "--apply" in sys.argv

# Articles that count as gift articles (EN handle).
_GIFT_HANDLE = re.compile(r"gift|stocking|geschenk", re.I)

_P = '<p class="velluto-night-glow-gift">'
TEXT = {
    "en": ('{p}A small, playful gift: <a href="{u}">Velluto Night Glow LED valve cap lights</a> '
           'turn a wheel into a ring of colour. A vibration sensor switches them on as soon as '
           'the wheel turns. A 2-pack for both wheels of one bike is 14.99 EUR, a 4-pack for two '
           'bikes 24.99 EUR. They fit Schrader and Dunlop valves, not Presta, so check the '
           "recipient's valves first. They are decorative and do not replace the lights and "
           'reflectors required by StVZO.</p>'),
    "de": ('{p}Ein kleines, verspieltes Geschenk: Die <a href="{u}">Velluto Night Glow '
           'LED-Ventilkappen</a> machen ein Rad zum leuchtenden Farbring. Ein Vibrationssensor '
           'schaltet sie ein, sobald sich das Rad dreht. Das 2er-Set für beide Räder eines '
           'Fahrrads kostet 14,99 €, das 4er-Set für zwei Fahrräder 24,99 €. Sie passen auf '
           'Auto- und Blitzventile, nicht auf Presta, also vorher die Ventile des Beschenkten '
           'prüfen. Sie sind Dekozubehör und ersetzen nicht die nach StVZO vorgeschriebene '
           'Beleuchtung und Reflektoren.</p>'),
    "nl": ('{p}Een klein, speels cadeau: de <a href="{u}">Velluto Night Glow LED-ventieldopjes</a> '
           'maken van een wiel een lichtgevende kleurring. Een trillingssensor schakelt ze in '
           'zodra het wiel draait. Een 2-pack voor beide wielen van één fiets kost 14,99 €, een '
           '4-pack voor twee fietsen 24,99 €. Ze passen op Schrader- en Dunlopventielen, niet op '
           'Presta, controleer dus eerst de ventielen van de ontvanger. Ze zijn decoratief en '
           'vervangen niet de volgens de StVZO verplichte verlichting en reflectoren.</p>'),
    "fr": ('{p}Un petit cadeau ludique : les <a href="{u}">bouchons de valve LED Velluto Night '
           'Glow</a> transforment une roue en anneau de couleur. Un capteur de vibrations les '
           'allume dès que la roue tourne. Le pack de 2 pour les deux roues d\'un vélo coûte '
           '14,99 €, le pack de 4 pour deux vélos 24,99 €. Ils conviennent aux valves Schrader '
           'et Dunlop, pas aux valves Presta : vérifiez d\'abord les valves du destinataire. Ils '
           'sont décoratifs et ne remplacent pas l\'éclairage et les catadioptres exigés par la '
           'StVZO.</p>'),
    "es": ('{p}Un regalo pequeño y divertido: las <a href="{u}">tapas de válvula LED Velluto '
           'Night Glow</a> convierten una rueda en un anillo de color. Un sensor de vibración '
           'las enciende en cuanto la rueda gira. El pack de 2 para las dos ruedas de una bici '
           'cuesta 14,99 €, el pack de 4 para dos bicis 24,99 €. Encajan en válvulas Schrader y '
           'Dunlop, no en Presta, así que comprueba antes las válvulas de quien lo recibe. Son '
           'decorativas y no sustituyen la iluminación y los reflectores exigidos por la '
           'StVZO.</p>'),
    "it": ('{p}Un regalo piccolo e giocoso: i <a href="{u}">tappi valvola LED Velluto Night '
           'Glow</a> trasformano una ruota in un anello di colore. Un sensore di vibrazione li '
           'accende appena la ruota gira. La confezione da 2 per le due ruote di una bici costa '
           '14,99 €, quella da 4 per due bici 24,99 €. Si adattano alle valvole Schrader e '
           'Dunlop, non alle Presta: controlla prima le valvole di chi riceve il regalo. Sono '
           'decorativi e non sostituiscono l\'illuminazione e i catadiottri richiesti dalla '
           'StVZO.</p>'),
    "da": ('{p}En lille, legende gave: <a href="{u}">Velluto Night Glow LED-ventilhætter</a> '
           'gør et hjul til en lysende farvering. En vibrationssensor tænder dem, så snart '
           'hjulet drejer. En 2-pak til begge hjul på én cykel koster 14,99 €, en 4-pak til to '
           'cykler 24,99 €. De passer på Schrader- og Dunlop-ventiler, ikke på Presta, så tjek '
           'modtagerens ventiler først. De er dekorative og erstatter ikke det lys og de '
           'reflekser, der kræves efter StVZO.</p>'),
    "nb": ('{p}En liten, leken gave: <a href="{u}">Velluto Night Glow LED-ventilhetter</a> gjør '
           'et hjul til en lysende fargering. En vibrasjonssensor slår dem på så snart hjulet '
           'går rundt. En 2-pakning til begge hjulene på én sykkel koster 14,99 €, en 4-pakning '
           'til to sykler 24,99 €. De passer på Schrader- og Dunlop-ventiler, ikke på Presta, så '
           'sjekk mottakerens ventiler først. De er dekorative og erstatter ikke lyset og '
           'reflekser som kreves etter StVZO.</p>'),
    "pl": ('{p}Mały, zabawny prezent: <a href="{u}">diodowe nakładki na wentyl Velluto Night '
           'Glow</a> zamieniają koło w świecący kolorowy pierścień. Czujnik wibracji włącza je, '
           'gdy tylko koło się obraca. Zestaw 2 sztuk na oba koła jednego roweru kosztuje 14,99 €, '
           'zestaw 4 sztuk na dwa rowery 24,99 €. Pasują do wentyli samochodowych (Schrader) i '
           'Dunlop, nie do Presta, więc najpierw sprawdź wentyle obdarowanej osoby. Są '
           'dekoracyjne i nie zastępują oświetlenia i odblasków wymaganych przez StVZO.</p>'),
    "pt-PT": ('{p}Uma prenda pequena e divertida: as <a href="{u}">tampas de válvula LED Velluto '
              'Night Glow</a> transformam uma roda num anel de cor. Um sensor de vibração liga-as '
              'assim que a roda gira. O pack de 2 para as duas rodas de uma bicicleta custa '
              '14,99 €, o pack de 4 para duas bicicletas 24,99 €. Servem em válvulas Schrader e '
              'Dunlop, não em Presta, por isso confirme primeiro as válvulas de quem recebe. São '
              'decorativas e não substituem a iluminação e os reflectores exigidos pela '
              'StVZO.</p>'),
    "sv": ('{p}En liten, lekfull present: <a href="{u}">Velluto Night Glow LED-ventilhättor</a> '
           'gör ett hjul till en lysande färgring. En vibrationssensor tänder dem så fort hjulet '
           'snurrar. Ett 2-pack till båda hjulen på en cykel kostar 14,99 €, ett 4-pack till två '
           'cyklar 24,99 €. De passar på Schrader- och Dunlop-ventiler, inte på Presta, så '
           'kontrollera mottagarens ventiler först. De är dekorativa och ersätter inte den '
           'belysning och de reflexer som krävs enligt StVZO.</p>'),
}

_H2 = re.compile(r"<h2\b", re.I)


def insert_paragraph(body: str, lang: str) -> tuple[str, bool]:
    """Insert the paragraph before section 03 (after the stocking-stuffer section).
    Returns (body, inserted). Already linked, or no usable anchor: unchanged."""
    if not body or "velluto-night-glow" in body:
        return body, False
    para = TEXT[lang].format(p=_P, u=URL)
    m = re.search(r'<h2 id="s3"', body)
    if m:
        pos = m.start()
    else:
        heads = [h.start() for h in _H2.finditer(body)]
        if len(heads) < 3:
            return body, False
        pos = heads[2]
    return body[:pos] + para + "\n\n" + body[pos:], True


def main() -> None:
    import requests
    from seo_bot import (BLOG_ID, SHOP_LOCALES, SHOPIFY_HEADERS, SHOPIFY_STORE,
                         get_translatable_digests, graphql_with_vars,
                         register_shopify_translation)

    api = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
    url = (f"{api}/blogs/{BLOG_ID}/articles.json"
           "?fields=id,title,handle,body_html&limit=250&published_status=published")
    arts = []
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        arts.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)

    gifts = [a for a in arts if _GIFT_HANDLE.search(a.get("handle", ""))]
    print(f"=== link_night_glow [{'APPLY' if APPLY else 'DRY-RUN'}] — "
          f"{len(gifts)} Geschenk-Artikel ===")
    done = 0
    for a in gifts:
        aid, body = a["id"], a.get("body_html") or ""
        new_body, ok = insert_paragraph(body, "en")
        if ok:
            print(f"  [en] {a['handle']}: Absatz einfügen")
            if APPLY:
                resp = requests.put(f"{api}/blogs/{BLOG_ID}/articles/{aid}.json",
                                    headers=SHOPIFY_HEADERS, timeout=30,
                                    json={"article": {"id": aid, "body_html": new_body}})
                print("     " + ("✅" if resp.status_code == 200 else f"❌ HTTP {resp.status_code}"))
                if resp.status_code == 200:
                    done += 1
        gid = f"gid://shopify/Article/{aid}"
        digests = None
        for loc in SHOP_LOCALES:
            if loc not in TEXT:
                continue
            res = graphql_with_vars(
                "query($id: ID!, $l: String!){ translatableResource(resourceId: $id)"
                "{ translations(locale: $l){ key value } } }", {"id": gid, "l": loc})
            tx = {t["key"]: t["value"] for t in
                  ((res.get("translatableResource") or {}).get("translations") or [])}
            t_body, ok = insert_paragraph(tx.get("body_html", ""), loc)
            if not ok:
                continue
            print(f"  [{loc}] {a['handle']}: Absatz einfügen")
            if APPLY:
                digests = digests or get_translatable_digests(aid)
                reg = register_shopify_translation(
                    aid, loc, title=tx.get("title", ""), body_html=t_body,
                    meta_desc=tx.get("meta_description", tx.get("summary_html", "")),
                    digests=digests)
                print("     " + ("✅" if reg else "❌"))
                done += 1 if reg else 0
    print(f"\n{done} Fassung(en) aktualisiert." if APPLY else "\nDRY-RUN — mit --apply schreiben.")


if __name__ == "__main__":
    main()
