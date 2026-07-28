# GSC Fix: „Nicht gefunden (404)" + neue Nicht-Indexierungs-Gründe (2026-07-28)

**Stand:** 2026-07-28 · **Betroffene Property:** `sc-domain:velluto-shop.com`
**Auslöser:** 2 GSC-Mails vom 28.07. (00:14 + 00:18 Uhr) · **Fix:** dieses Repo

---

## 1. Was Google gemeldet hat

| Mail | Meldung |
|---|---|
| 00:18 | **„Nicht gefunden (404)"** — Quelle: **eine Sitemap** |
| 00:14 | Neue Gründe: **„Wegen eines anderen 4xx-Problems blockiert"** + **„Indexiert, obwohl durch robots.txt-Datei blockiert"** |

## 2. Diagnose (live verifiziert, 2026-07-28)

### a) 404 in einer Sitemap — Ursache: Legal-Drafting (beabsichtigt)

`legal_retrofit.py --rewrite` konnte für
`best-oakley-alternatives-for-cyclists-2026-tested-ranked` **keinen sauberen
Rewrite** erzeugen und hat den Artikel bewusst auf **Draft** gelassen
(`legal_rewrite.log`: „no clean edit produced — keep it drafted"). Folge:

- Die URL liefert **404 in allen 12 Locales** (live geprüft: EN/de/fr/it/nl → 404).
- Google hatte die URL noch aus der Sitemap, bevor Shopify sie entfernt hat →
  Meldung „404 … in einer Sitemap".
- **Selbstheilend:** Shopify pflegt die Sitemap in Echtzeit. Live geprüft:
  Die Draft-URL ist **nicht mehr** in `sitemap_blogs_1.xml`; alle 45 gelisteten
  EN-Blog-URLs liefern **200**. Der 404 ist beabsichtigt (Legal geht vor) und
  das **korrekte** Signal an Google zum De-Indexieren.

**Aber — echter Folgeschaden gefunden:** 2 veröffentlichte Artikel verlinkten
noch auf die gedraftete URL (tote interne Links → Googlebot crawlt den 404
immer wieder, Linkjuice verpufft):

- `best-road-cycling-glasses-2026-tested-ranked`
- `best-cycling-glasses-value-2026-oakley-vs-velluto-vs-decathlon`

### b) „Indexiert, obwohl durch robots.txt-Datei blockiert" — nicht Bot-verursacht

Shopifys **Standard-robots.txt** (inkl. des neuen Agent-Commerce-Blocks 2026)
disallowt u. a. `/checkout`, `/cart/`, `/account`, `/orders`, `/62156079275`,
`/cdn/wpm/*.js`, `/services`, `/sf_*`. URLs darunter, die Google früher kannte
oder über externe Links findet, landen in diesem Report. Das Repo schreibt
keine robots.txt und verlinkt keine dieser Pfade (geprüft). **Normalerweise
keine Aktion nötig** — transaktionale Seiten sollen nicht ranken; Google räumt
den Report über Wochen selbst auf. Nur handeln, wenn im Report **echte
Content-URLs** (Blog/Produkt/Collection) auftauchen.

### c) „Wegen eines anderen 4xx-Problems blockiert" — URLs nur im GSC-Report sichtbar

„Anderes 4xx" = alles außer 401/403/404, praktisch meist **429/430**
(Shopifys Bot-/Rate-Limit-Schutz drosselt Googlebot kurzzeitig). Transient und
ohne Repo-Bezug. **Aktion:** Report öffnen, betroffene URLs ansehen; sind es
Content-URLs, per URL-Prüfung „Live-URL testen" — liefert sie 200, „Behebung
validieren" klicken.

## 3. Fixes in diesem Repo (Branch `claude/velluto-gsc-issues-phn2W`)

1. **Neu: `scripts/scrub_drafted_links.py`** — entfernt interne Links auf
   gedraftete Artikel aus allen veröffentlichten EN-Bodies **und** allen
   Locale-Übersetzungen (Anker-Text bleibt, `<a>` fällt weg; optional
   `--retarget <live-URL>` mit Self-Link-Schutz). Prüft zusätzlich die
   Blog-Sitemap auf Nicht-200-URLs. Idempotent, Dry-Run per Default.
2. **`legal_retrofit.py`**: Beide Draft-Pfade weisen jetzt explizit darauf hin,
   dass die gedraftete URL ab sofort 404 liefert und eingehende interne Links
   gescrubbt werden sollten (bzw. übersprungen, wenn zeitnah re-published wird).
3. **`link_builder.py`**: toter Sitemap-Ping-Kanal entfernt — Googles
   `/ping`-Endpoint ist seit Mitte 2023 abgeschaltet (täglich `http_404` im
   Log), Bings liefert `410`. Discovery läuft über die in GSC registrierte
   Sitemap.

## 4. Ausführen (VPS)

```bash
cd ~/velluto-seo-bot && git pull

python3 scripts/scrub_drafted_links.py           # Dry-Run: zeigt tote Links + Sitemap-Check
python3 scripts/scrub_drafted_links.py --apply   # entfernt sie (EN + alle Locales)

# Optional statt Unwrap: Links auf den thematisch nächsten Live-Artikel umbiegen
python3 scripts/scrub_drafted_links.py --apply \
  --retarget https://velluto-shop.com/blogs/velluto-the-magazine/best-cycling-glasses-value-2026-oakley-vs-velluto-vs-decathlon

# Jederzeit ohne Shopify-Credentials: reiner Sitemap-Gesundheitscheck
python3 scripts/scrub_drafted_links.py --sitemap-only
```

**Wichtig:** Wird der Oakley-Artikel demnächst compliant neu geschrieben und
re-published (`legal_retrofit.py --republish-clean`), Scrub **überspringen** —
entfernte Links kommen beim Republish nicht zurück.

## 5. In der Search Console

1. Indexierung → Seiten → **„Nicht gefunden (404)"** → Report öffnen →
   bestätigen, dass nur die 12 Locale-Varianten der Draft-URL gelistet sind →
   **„Behebung validieren"**. (Der 404 selbst bleibt — beabsichtigt. Für
   schnelleres De-Indexieren optional: Entfernungen → URL-Präfix der Draft-URL.)
2. **„Indexiert, obwohl durch robots.txt blockiert"** → URLs prüfen: nur
   Cart/Checkout/Account/CDN-Pfade? → ignorieren, läuft von selbst leer.
3. **„Anderes 4xx"** → URLs prüfen wie in 2c beschrieben.

## 6. Erwartung

- 404-Report: leert sich nach Validierung binnen 1–4 Wochen.
- robots.txt-Report: fluktuiert, solange Shopify transaktionale Pfade blockt —
  unkritisch, kein Ranking-Einfluss auf Content-Seiten.
- Tote interne Links: nach `--apply` sofort weg (EN + 10 Locales), Googlebot
  findet den 404 nicht mehr über interne Pfade.
