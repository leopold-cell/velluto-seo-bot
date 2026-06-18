# Magazine Layout Fix: Artikel links-ausgerichtet + ungleiche Listing-Kacheln (Desktop)

**Stand:** 2026-06-13 · **Betroffen:** `velluto-shop.com` Magazine (Desktop)
**Gilt für:** Live-Shopify-Theme — **nicht** dieses Repo. Diese Datei ist die
Diagnose + Schritt-für-Schritt-Anleitung zur Umsetzung durch **Velluto Autopilot**
(voller Theme-Zugriff).

> **Wichtig:** Dieses Repo enthält nur die **Artikel-Section** des Magazines
> (`theme/sections/velluto-magazine-article.liquid` + `theme/assets/velluto-magazine.css`).
> Der **globale Theme-Wrapper** und das **Blog-Listing-Template** liegen **nicht** hier,
> und der Workflow `daily-blog.yml` macht **keinen `shopify theme push`**. Beide Fehler
> sind daher aus diesem Repo **nicht direkt deploybar** und müssen im Live-Theme behoben
> werden.

---

## Gemeldete Symptome

1. **Blogartikel sind auf Desktop links ausgerichtet** statt zentriert.
2. **Überblicksbild-Kacheln** auf der Magazine-Übersicht (`/blogs/velluto-the-magazine`)
   sind **ungleich groß**.

---

## Diagnose (verifiziert)

- Die Live-Artikel rendern über das Repo-Template `velluto-magazine-article`
  (live bestätigt: AUTOR/KATEGORIE-Zeile, „Ride Fast. Live Slow.", „Keep reading",
  Contents-TOC).
- Die Artikel-CSS `velluto-magazine.css` **zentriert korrekt**:
  `.vmag-wrap{ max-width:840px; margin:0 auto }` (bestätigt durch die identische
  `theme/preview/index.html`). → Die Links-Ausrichtung kommt **nicht** aus der
  Section-CSS, sondern vom **globalen Theme-Content-Wrapper** außenrum.
- Das **Blog-Listing-Template** ist nicht Teil dieser Section; die `.vmag`-CSS ist dort
  gar nicht geladen. → Ungleiche Kacheln = Listing-Template / Card-Snippet im Live-Theme.
- Repo-Theme-Dateien seit **2026-05-28** unverändert → die „neue" Regression entstand im
  Live-Theme (globaler Wrapper bzw. eine abweichende deployte CSS-Version).

---

## Problem A — Artikel links ausgerichtet (Desktop)

**Ursache:** Der globale Content-Wrapper um die `velluto-magazine-article`-Section richtet
Full-Width-Sections links aus bzw. verengt sie (z. B. Wrapper auf `display:flex`/`grid`
ohne Zentrierung, oder ein `page-width`-Container ohne `margin-inline:auto`). Die
Section-CSS selbst ist korrekt.

**✅ Fix ist bereits implementiert** in `theme/assets/velluto-magazine.css` (parent-unabhängige,
mobile-first Bulletproof-Zentrierung): `.vmag-main` nimmt volle Breite + zentriert, und per
`@supports selector(:has(*))` werden gängige Shopify-Content-Wrapper
(`#MainContent`, `.content-for-layout`, `main[role="main"]`, `.shopify-section:has(>.vmag-main)`)
**nur auf Magazine-Seiten** von ihrer Links-/Max-Width-Zwängung befreit. `.vmag-wrap` bleibt
`max-width` + `margin:auto`.

**Es fehlt nur noch der Deploy** dieser Datei ins Live-Theme:
```bash
shopify theme push --only assets/velluto-magazine.css --nodelete
```

Falls nach dem Deploy noch immer links: Der globale Wrapper nutzt einen **anderen**
Klassen-/ID-Namen als die oben abgedeckten — dann diesen Selektor in der `:has()`-Liste in
`velluto-magazine.css` ergänzen (Name per DevTools am `<main>`/Wrapper-Element ablesen).

---

## Problem B — Listing-Kacheln ungleich groß

**Ursache:** Das Blog-Listing-Template rendert die Karten-Bilder im **natürlichen
Seitenverhältnis** ohne fixes `aspect-ratio` / `object-fit`, daher unterschiedliche Höhen.

**Gewünschtes Format: quadratisch (1:1).** Alle Übersichts-Kacheln sollen **1:1** sein.

**Fix im Live-Theme** (Blog-Listing-Section bzw. Article-Card-Snippet, z. B.
`sections/main-blog.liquid` / `snippets/article-card.liquid`):

```css
/* Karten-Thumbnail auf einheitliches 1:1-Format zwingen */
.blog-card__image,
.article-card img {
  aspect-ratio: 1 / 1;   /* quadratische Kacheln, alle gleich groß */
  width: 100%;
  height: 100%;
  object-fit: cover;     /* schneidet zu, statt zu verzerren/zu stauchen */
}
```

- Grid mit gleichen Spalten-Tracks sicherstellen:
  `grid-template-columns: repeat(4, 1fr);` und `align-items: stretch;` damit Karten gleich
  hoch sind.
- Bild-Container ggf. `overflow:hidden`, damit `object-fit:cover` sauber zuschneidet.

---

## Acceptance Criteria

- [ ] Artikel auf Desktop **zentriert** (mehrere Beiträge, Breite ≥ 960 px)
- [ ] Alle Listing-Kacheln **quadratisch (1:1) und gleich groß**
- [ ] Responsiv geprüft bei **640 / 960 / 1440 px** — kein Links-Versatz, gleichmäßiges Grid
- [ ] Änderungen im **Live-Theme deployed** (`shopify theme push`)

---

## Verifizierung

1. 2–3 Artikel auf Desktop öffnen → Inhalt zentriert.
2. `https://velluto-shop.com/blogs/velluto-the-magazine` öffnen → alle Kachelbilder gleich groß.
3. Browser-Resize 640 / 960 / 1440 px → kein Links-Versatz, gleichmäßiges Grid.
