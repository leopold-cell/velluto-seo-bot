# GSC Fix: „Duplikat – Google hat eine andere Seite als der Nutzer als kanonische Seite bestimmt"

**Stand:** 2026-07-06 · **Betroffene Property:** `sc-domain:velluto-shop.com`
**Betroffen:** Blog-/Magazin-Artikel (alle Locale-Varianten) · **Fix:** dieses Repo (kein Theme-Eingriff)

---

## 1. Was Google gemeldet hat

GSC → Indexierung → Seiten: Blog-Artikel-URLs landen unter **„Duplikat – Google hat eine
andere Seite als der Nutzer als kanonische Seite bestimmt"** — Google ignoriert den vom
Bot deklarierten Canonical und wählt selbst eine andere URL als kanonisch.

## 2. Ursache (live verifiziert, 2026-07-06)

`build_body_html()` in `seo_bot.py` injizierte ein **client-seitiges JavaScript** in jeden
Artikel-Body, das zur Laufzeit ein `<link rel="canonical">` an `document.head` anhängt.
Das Script strippte den Locale-Präfix und ließ **jede** Übersetzung auf die **englische
Root-URL** zeigen.

Das kollidierte mit dem, was Shopify ohnehin korrekt server-seitig rendert:

| Signal | Server (Shopify, korrekt) | JS-Inject (Bot, falsch) |
|---|---|---|
| Canonical auf `/de/blogs/...` | `/de/blogs/...` (self-referencing) | `/blogs/...` (EN-Root) |
| hreflang | vollständig: 11 Locales + x-default | — |

**Regel:** Seiten in einem hreflang-Set müssen sich **selbst** kanonisieren. Eine
Übersetzung, die per Canonical auf eine andere Sprache zeigt, bricht hreflang → Google
verwirft den deklarierten Canonical und entscheidet selbst → exakt die gemeldete Meldung.

## 3. Fix (2026-07-06, Branch `claude/velluto-gsc-issues-phn2W`)

1. **Neu-Artikel:** JS-Canonical-Injektion aus `build_body_html()` entfernt.
   Shopifys server-seitiger Canonical + hreflang übernehmen — die sind bereits korrekt.
2. **Bestand:** `scripts/backfill_seo_cleanup.py` entfernt das injizierte Script aus allen
   veröffentlichten Artikeln **und** deren Translate&Adapt-Übersetzungen:
   ```bash
   python3 scripts/backfill_seo_cleanup.py            # Dry-Run (Report, schreibt nichts)
   python3 scripts/backfill_seo_cleanup.py --apply    # schreibt; legt vorher JSON-Backup an
   # Notfall-Restore:
   python3 scripts/backfill_seo_cleanup.py --restore output/backfill_backups/<datei>.json
   ```
3. **Rückfall-Schutz:** `review/seo_geo_audit.py` (läuft im 28-Tage-Review) flaggt jetzt
   (a) Canonicals, die nicht self-referencing sind, und (b) jeden JS-injizierten Canonical.

## 4. Validieren

1. Quelltext eines Locale-Artikels (`/de/blogs/...`) prüfen:
   - genau **ein** `<link rel="canonical">`, zeigt auf die **eigene** `/de/…`-URL
   - **kein** `l.rel="canonical"`-Script im Body
   - hreflang-Set unverändert (11 Locales + x-default)
2. GSC → Indexierung → Seiten → Report „Duplikat – Google hat eine andere Seite …" →
   **„Behebung validieren"**. Google crawlt über mehrere Wochen neu.

## 5. Erwartung / Übergang

2–6 Wochen Fluktuation sind normal: Signale, die bisher fälschlich auf der EN-URL
konsolidiert waren, verteilen sich auf die Sprachversionen. Zielbild: jede Locale-URL
rankt in ihrem Markt (hreflang-konform), der Duplikat-Report läuft leer.
