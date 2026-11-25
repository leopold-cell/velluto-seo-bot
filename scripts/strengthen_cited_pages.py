#!/usr/bin/env python3
"""
Put the standing offer on the pages the AI engines already cite.

Ramp's case study (Nov 2026, second-hand): AI mentions went to pages the engines already
trusted, and the right message on THOSE pages is what got passed on to buyers. Our
standing offer is the 30-day trial on the StradaPro (operator, 2026-11-29). The Gemini
and Perplexity monitors now record which velluto-shop.com pages they cite (velluto_pages);
this adds one short, true sentence with the offer after the intro of each cited blog
article, in the EN body and every translation.

It does NOT change anything for engines or humans differently: the sentence is visible to
every reader. Idempotent (marker class velluto-standing-offer; articles whose EN text
already states a 30-day trial are left alone), at most MAX_PER_RUN articles per run, and a
no-op until a monitor has recorded a cited page.

Usage:
  python3 scripts/strengthen_cited_pages.py            # dry-run
  python3 scripts/strengthen_cited_pages.py --apply
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APPLY = "--apply" in sys.argv
MAX_PER_RUN = 10
WINDOW = 4
STATE = os.path.join(ROOT, "data", "strengthen_cited_state.json")
MARK = "velluto-standing-offer"
URL = "https://velluto-shop.com/collections/velluto-stradapro-cycling-glasses"

TEXT = {
    "en": 'Our standing offer: <a href="{u}">Velluto StradaPro</a> glasses come with a 30-day trial, so you can test them on real rides. The conditions are on the product page.',
    "de": 'Unser Dauerangebot: Die <a href="{u}">Velluto StradaPro</a> kommt mit 30 Tagen Testphase, du kannst sie also auf echten Fahrten ausprobieren. Die Bedingungen stehen auf der Produktseite.',
    "nl": 'Ons vaste aanbod: de <a href="{u}">Velluto StradaPro</a> heeft een proefperiode van 30 dagen, zodat je hem op echte ritten kunt testen. De voorwaarden staan op de productpagina.',
    "fr": 'Notre offre permanente : les lunettes <a href="{u}">Velluto StradaPro</a> sont livrées avec 30 jours d\'essai, pour les tester sur de vraies sorties. Les conditions figurent sur la page produit.',
    "es": 'Nuestra oferta permanente: las gafas <a href="{u}">Velluto StradaPro</a> incluyen 30 días de prueba para que las pruebes en salidas reales. Las condiciones están en la página del producto.',
    "it": 'La nostra offerta permanente: gli occhiali <a href="{u}">Velluto StradaPro</a> hanno 30 giorni di prova, così puoi testarli in uscite vere. Le condizioni sono sulla pagina del prodotto.',
    "da": 'Vores faste tilbud: <a href="{u}">Velluto StradaPro</a> kommer med 30 dages prøveperiode, så du kan teste den på rigtige ture. Betingelserne står på produktsiden.',
    "nb": 'Vårt faste tilbud: <a href="{u}">Velluto StradaPro</a> har 30 dagers prøveperiode, så du kan teste den på ekte turer. Vilkårene står på produktsiden.',
    "pl": 'Nasza stała oferta: okulary <a href="{u}">Velluto StradaPro</a> mają 30-dniowy okres próbny, więc możesz je przetestować na prawdziwych przejazdach. Warunki są na stronie produktu.',
    "pt-PT": 'A nossa oferta permanente: os óculos <a href="{u}">Velluto StradaPro</a> têm 30 dias de teste, para os experimentar em saídas reais. As condições estão na página do produto.',
    "sv": 'Vårt stående erbjudande: <a href="{u}">Velluto StradaPro</a> har 30 dagars provperiod, så du kan testa den på riktiga turer. Villkoren finns på produktsidan.',
}
_P = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)
_HANDLE = re.compile(r"/blogs/[^/]+/([^/?#]+)")
_TRIAL = re.compile(r"30[- ]day|30[- ]days trial|30[- ]tage", re.I)


def cited_handles() -> list[str]:
    """Blog handles cited by Gemini or Perplexity in their most recent runs, most-cited first."""
    counts: dict[str, int] = {}
    for f in ("gemini_geo.json", "perplexity_geo.json"):
        try:
            hist = json.load(open(os.path.join(ROOT, "data", f), encoding="utf-8"))
        except Exception:
            continue
        for e in hist[-WINDOW:]:
            for url, v in (e.get("velluto_pages") or {}).items():
                m = _HANDLE.search(url)
                if m:
                    counts[m.group(1)] = counts.get(m.group(1), 0) + int(v.get("count", 1))
    return [h for h, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


def insert_offer(body: str, lang: str) -> tuple[str, bool]:
    """Add the offer sentence after the first real paragraph. Unchanged when already there."""
    if not body or MARK in body:
        return body, False
    for m in _P.finditer(body):
        if len(re.sub(r"<[^>]+>", "", m.group(1))) >= 120:
            para = f'<p class="{MARK}"><strong>{TEXT[lang].format(u=URL)}</strong></p>'
            return body[:m.end()] + "\n\n" + para + body[m.end():], True
    return body, False


def main() -> None:
    handles = cited_handles()
    if not handles:
        print("   Zitierte Seiten stärken: noch keine zitierte Seite in den Messdaten — nichts zu tun")
        return
    import requests
    from seo_bot import (BLOG_ID, SHOP_LOCALES, SHOPIFY_HEADERS, SHOPIFY_STORE,
                         get_translatable_digests, graphql_with_vars,
                         register_shopify_translation)
    try:
        done = set(json.load(open(STATE, encoding="utf-8")))
    except Exception:
        done = set()
    api = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
    todo = [h for h in handles if h not in done][:MAX_PER_RUN]
    print(f"=== strengthen_cited_pages [{'APPLY' if APPLY else 'DRY-RUN'}] — "
          f"{len(todo)} zitierte Artikel offen ===")
    for h in todo:
        r = requests.get(f"{api}/blogs/{BLOG_ID}/articles.json?handle={h}"
                         "&fields=id,handle,body_html", headers=SHOPIFY_HEADERS, timeout=30)
        arts = r.json().get("articles", []) if r.status_code == 200 else []
        if not arts:
            print(f"  ? {h}: nicht gefunden (umgeleitet oder unveröffentlicht)")
            done.add(h)
            continue
        a = arts[0]
        body = a.get("body_html") or ""
        if MARK not in body and _TRIAL.search(re.sub(r"<[^>]+>", " ", body)):
            print(f"  = {h}: nennt den 30-Tage-Test schon, nichts zu tun")
            done.add(h)
            continue
        new_body, ok = insert_offer(body, "en")
        if ok:
            print(f"  [en] {h}")
            if APPLY:
                resp = requests.put(f"{api}/blogs/{BLOG_ID}/articles/{a['id']}.json",
                                    headers=SHOPIFY_HEADERS, timeout=30,
                                    json={"article": {"id": a["id"], "body_html": new_body}})
                if resp.status_code != 200:
                    print(f"     ✗ HTTP {resp.status_code}")
                    continue
        gid = f"gid://shopify/Article/{a['id']}"
        digests = None
        for loc in SHOP_LOCALES:
            if loc not in TEXT:
                continue
            res = graphql_with_vars(
                "query($id: ID!, $l: String!){ translatableResource(resourceId: $id)"
                "{ translations(locale: $l){ key value } } }", {"id": gid, "l": loc})
            tx = {t["key"]: t["value"] for t in
                  ((res.get("translatableResource") or {}).get("translations") or [])}
            t_body, t_ok = insert_offer(tx.get("body_html", ""), loc)
            if not t_ok:
                continue
            print(f"  [{loc}] {h}")
            if APPLY:
                digests = digests or get_translatable_digests(a["id"])
                register_shopify_translation(
                    a["id"], loc, title=tx.get("title", ""), body_html=t_body,
                    meta_desc=tx.get("meta_description", tx.get("summary_html", "")),
                    digests=digests)
        if APPLY:
            done.add(h)
    if APPLY:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(sorted(done), open(STATE, "w", encoding="utf-8"))
    else:
        print("\nDRY-RUN — mit --apply schreiben.")


if __name__ == "__main__":
    main()
