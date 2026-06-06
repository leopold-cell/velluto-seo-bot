# GSC Fix: Strukturierte-Daten-Fehler auf den Produktseiten (velluto-shop.com)

**Stand:** 2026-06-06 · **GSC-Message-Type:** `WNC-10030322`
**Betroffene Property:** `velluto-shop.com` (Shopify)
**Gilt für:** Live-Shopify-Theme (Produkt-Templates) — **nicht** dieses Repo. Dieses
Dokument ist die Schritt-für-Schritt-Anleitung zum internen Einspielen.

> **Wichtig:** Der SEO-Bot in diesem Repo erzeugt **nur Blog-/Magazin-Inhalte**. Die
> hier beschriebenen Fehler stammen aus dem **Produkt-JSON-LD** des Live-Themes bzw.
> einer Reviews-App und müssen direkt im Shopify-Theme behoben werden. Der lokale
> `theme/`-Ordner ist laut `.shopifyignore` nur ein Teil-Backup der Blog-Dateien und
> enthält die Produkt-Templates bewusst nicht.

---

## 1. Was Google gemeldet hat (3 Mails, 06.06.2026)

| Report (GSC → Verbesserungen) | Anzahl | Problem | Schweregrad |
|---|---|---|---|
| **Händlereinträge** (Merchant listings) | 3 | **Feld `brand` doppelt** | 🔴 kritisch |
| | | Rezension hat mehrere zusammengefasste Bewertungen (in `review`) | 🟡 nicht kritisch |
| | | Rezension hat mehrere zusammengefasste Bewertungen (in `aggregateRating`) | 🟡 nicht kritisch |
| **Rezensions-Snippets** (Review snippets) | 1 | **Rezension hat mehrere zusammengefasste Bewertungen** | 🔴 kritisch |
| **Produkt-Snippets** (Product snippets) | 2 | Rezension hat mehrere zusammengefasste Bewertungen (`review` + `aggregateRating`) | 🟡 nicht kritisch |

Trotz fünf gemeldeter Zeilen sind es im Kern **zwei** Ursachen:

1. **`brand` ist im Product-Markup doppelt vorhanden.**
2. **Pro Produkt existiert mehr als eine `aggregateRating` / zusammengefasste Bewertung.**

🔴 **Kritisch** = das Rich-Result (Sterne, Preis, Händler-Snippet) wird in der Google-Suche
**nicht mehr angezeigt** → direkter Klick-/Sichtbarkeitsverlust.

---

## 2. Ursachenanalyse

Beide Fehler entstehen fast immer dadurch, dass **zwei Quellen gleichzeitig** Produkt-
JSON-LD ausgeben:

- **Quelle A — das Theme:** Viele Shopify-Themes (Dawn-Derivate) rendern im
  Produkt-Template ein `Product`-JSON-LD inkl. `brand` und teils `aggregateRating`.
- **Quelle B — eine App / Shopifys natives Markup:** Reviews-Apps (Judge.me, Loox,
  Okendo, Yotpo …) injizieren ihr **eigenes** `aggregateRating`/`review`, und/oder eine
  „JSON-LD for SEO"-App bzw. Shopifys nativer Strukturdaten-Output ergänzt nochmals
  `brand`.

Ergebnis: Google sieht **zwei `brand`-Werte** und **zwei zusammengefasste Bewertungen**
für dieselbe Produkt-Entität → genau die gemeldeten Fehler.

**Ziel:** Pro Produktseite darf es **genau ein** `Product`-Objekt mit **genau einem**
`brand` und **genau einem** `aggregateRating` geben.

---

## 3. Fix A — Doppeltes `brand` entfernen (🔴 kritisch)

### Schritt 1 — Quelle finden
Shopify Admin → **Online Store → Themes → … → Edit code**. Suche im Code (Lupe oben links)
nacheinander nach:

```
"brand"
application/ld+json
aggregateRating
```

Typische Fundorte:
- `sections/main-product.liquid`
- `snippets/product-media-gallery.liquid` oder ein eigenes `snippets/structured-data*.liquid`
- App-Embeds unter `Theme-Einstellungen → App-Einbettungen` (Reviews-/SEO-App)
- Shopifys nativer Block (in neueren Themes via `{{ product | structured_data }}` oder
  manuell aufgebautes JSON-LD)

### Schritt 2 — Entscheiden, welche Quelle bleibt
Behalte **eine** vollständige `Product`-JSON-LD-Quelle (Empfehlung: die des Themes, weil sie
Preis/Verfügbarkeit korrekt aus dem Produkt zieht) und **entferne `brand` aus allen anderen**
JSON-LD-Blöcken — oder deaktiviere den doppelten Block ganz.

### Schritt 3 — `brand` korrekt setzen (genau einmal)
```liquid
"brand": {
  "@type": "Brand",
  "name": {{ product.vendor | default: 'Velluto' | json }}
},
```
- `product.vendor` ist in Shopify das Marken-/Herstellerfeld. Wenn der Vendor nicht
  überall „Velluto" ist, hart auf `"Velluto"` setzen.
- `brand` darf im selben `Product`-Objekt **nur einmal** als Schlüssel vorkommen
  (doppelte Keys in einem JSON-Objekt sind ungültig und lösen genau diese Warnung aus).

---

## 4. Fix B — Mehrfache `aggregateRating` / Bewertungen entfernen (🔴 kritisch)

Pro Produkt ist **nur eine** zusammengefasste Bewertung erlaubt. Wähle **eine** der beiden
Varianten — **nicht beide gleichzeitig** laufen lassen:

### Variante 1 (empfohlen) — Reviews-App liefert die Bewertung, Theme nicht
1. In der Reviews-App (Judge.me / Loox / Okendo / Yotpo) die Option
   **„Rich snippets / SEO / structured data"** aktiviert lassen.
2. Im **Theme** jedes manuell gerenderte `"aggregateRating"` und `"review"` aus dem
   Product-JSON-LD **entfernen**, damit nicht doppelt ausgegeben wird.

### Variante 2 — Theme liefert die Bewertung, App-Snippet aus
1. In der Reviews-App die Rich-Snippet-/Structured-Data-Option **deaktivieren**.
2. Im Theme **genau ein** `aggregateRating` führen (siehe Snippet unten).

> Egal welche Variante: Am Ende darf der Quelltext der Produktseite **nur einen einzigen**
> `aggregateRating`-Block enthalten. Mit „Seitenquelltext anzeigen" + Strg/Cmd+F nach
> `aggregateRating` gegenprüfen → darf **genau 1 Treffer** liefern.

---

## 5. Referenz: ein einziges, valides Product-JSON-LD

So sollte am Ende **ein** Block auf der Produktseite aussehen (Theme-Liquid-Version mit nur
**einem** `brand` und **einem** `aggregateRating`):

```liquid
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "Product",
  "name": {{ product.title | json }},
  "image": [{{ product.featured_image | image_url: width: 1200 | prepend: "https:" | json }}],
  "description": {{ product.description | strip_html | truncate: 300 | json }},
  "sku": {{ product.selected_or_first_available_variant.sku | json }},
  "brand": {
    "@type": "Brand",
    "name": {{ product.vendor | default: 'Velluto' | json }}
  },
  "offers": {
    "@type": "Offer",
    "url": {{ shop.url | append: product.url | json }},
    "priceCurrency": {{ cart.currency.iso_code | json }},
    "price": {{ product.selected_or_first_available_variant.price | money_without_currency | strip_html | json }},
    "availability": "{% if product.available %}https://schema.org/InStock{% else %}https://schema.org/OutOfStock{% endif %}"
  }
  {%- if product.metafields.reviews.rating_count and product.metafields.reviews.rating_count.value > 0 -%}
  ,
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": {{ product.metafields.reviews.rating.value.rating | json }},
    "reviewCount": {{ product.metafields.reviews.rating_count.value | json }}
  }
  {%- endif -%}
}
</script>
```

Hinweise:
- Das `aggregateRating` wird **nur** ausgegeben, wenn es tatsächlich Bewertungen gibt
  (`rating_count > 0`) — sonst meldet Google „leere/ungültige Bewertung".
- Die Metafield-Pfade (`product.metafields.reviews.*`) gelten für **Shopify Product Reviews
  / kompatible Apps**. Bei Judge.me/Loox/Okendo stattdessen deren App-Snippet nutzen und im
  Theme gar kein `aggregateRating` rendern (= Variante 1 oben).

---

## 6. Validieren

1. **Rich Results Test:** https://search.google.com/test/rich-results → Produkt-URL
   einfügen → prüfen, dass **kein** „brand doppelt" und **nur ein** `aggregateRating`
   gemeldet wird.
2. **Seitenquelltext** der Produktseite öffnen → Strg/Cmd+F:
   - `"brand"` → erwartet **1 Treffer** pro Product-Block
   - `aggregateRating` → erwartet **1 Treffer**
3. **GSC → Verbesserungen** → jeweils „Händlereinträge", „Rezensions-Snippets",
   „Produkt-Snippets" öffnen → Button **„Behebung validieren"** klicken.
   Google prüft dann über mehrere Tage erneut; der Status wechselt auf „Bestanden".

---

## 7. Checkliste

- [ ] Doppelte JSON-LD-Quelle identifiziert (Theme vs. App vs. Shopify nativ)
- [ ] `brand` kommt pro Product-Block nur **einmal** vor
- [ ] `aggregateRating` kommt pro Produktseite nur **einmal** vor
- [ ] Reviews-App-Rich-Snippets entweder im Theme **oder** in der App — nicht beides
- [ ] Rich Results Test grün (mind. 2–3 Beispielprodukte)
- [ ] „Behebung validieren" in allen drei GSC-Berichten angestoßen
