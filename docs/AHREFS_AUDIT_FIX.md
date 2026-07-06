# Ahrefs Site-Audit Fix (Report 01.07.2026)

**Stand:** 2026-07-06 · **Quelle:** Ahrefs Site Audit `velluto-shop.com` (173 tracked issues)
**Diagnose:** Live-Sampling per curl + Code-Analyse · Branch `claude/velluto-gsc-issues-phn2W`

---

## 1. Übersicht: Issue → Ursache → Status

| Ahrefs-Issue (Crawled / Δ) | Ursache | Status |
|---|---|---|
| Meta description missing (715, +154) · Indexable not in sitemap (726, +154) | **Tag-Seiten-Bloat:** Artikel-Keyword wurde als Shopify-Tag gesetzt → pro Artikel neue dünne `/tagged/<keyword>`-Seite ×11 Locales (indexierbar, ohne Meta, nicht in Sitemap). +154 ≈ 14 Artikel × 11 Locales | ✅ gefixt (Zukunft): Tags auf festes Set geklemmt (`_safe_tags`, `ALLOWED_TAGS` in `seo_bot.py`). Bestand-Tags bewusst behalten (kein 404-Spike) |
| Multiple H1 tags (376, +110) | Body enthielt `<h1>` + Theme rendert Artikel-Titel als `<h1 class="hero-title">` → 2 H1s. Alt-Validator **forderte** sogar ein Body-H1 | ✅ gefixt: Validator umgedreht (Body-H1 = Fehler), Prompts angepasst; Bestand via `backfill_seo_cleanup.py` (h1→h2) |
| GSC-Canonical-Duplikat (verwandt) | JS-injizierter Canonical | ✅ siehe `docs/GSC_CANONICAL_FIX.md` |
| Page has links to redirect (290) · links to broken page (10) · 404 (10) | Links in Artikel-Bodies auf redirectende/tote URLs | 🔧 Diagnose+Fix im Backfill: `--check-links` (Report) / `--fix-links` (interne Redirects → finale URL; 404s werden nur gemeldet) |
| Missing alt text (1.793, +264) | ~5 Bilder **pro Seite** ohne alt — auch auf Produktseiten → globale **Theme**-Bilder (Header/Footer/Chrome), nicht Artikel-Bodies (Live-Check: Bodies OK). +264 = neue Seiten × dieselben 5 Bilder | ❌ **Theme-seitig** (s. Abschnitt 2) |
| Meta too long (44) / too short (20) / Title short (28) | Feintuning einzelner Seiten | ⏳ niedrige Prio — `meta_optimizer.py` läuft täglich und zieht nach |
| Slow page (6), CSS file size (1), Image file size (8) | Theme/Apps/Plattform | ❌ Theme-seitig (s. Abschnitt 2) |
| HTTP→HTTPS (2), 3XX (17), Redirect chain (1) | Shopify-Domain-/Plattform-Redirects | ℹ️ normal, keine Aktion |
| „…changed"-Zeilen (Meta/Title/H1/Word count) | Tracking-Info, keine Fehler. **Hinweis:** nach dem Backfill-`--apply` gibt es hier einen einmaligen Spike | ℹ️ erwartbar, ignorieren |

## 2. Theme-seitige Restpunkte (nicht dieses Repo)

Die Produkt-/Layout-Templates sind laut `.shopifyignore` bewusst nicht im Repo. Im
Shopify-Admin (Online Store → Themes → Edit code) zu beheben:

1. **~5 Chrome-Bilder ohne `alt`** (Header/Footer/Logo/Icons — erklärt ~1.700 der 1.793
   Instanzen): in den betroffenen Snippets `alt="Velluto — …"` ergänzen; bei rein
   dekorativen Bildern `alt=""` (leer ist ok, fehlend nicht).
2. **Slow pages / CSS size:** Apps-Audit (ungenutzte App-Embeds deaktivieren), Bilder
   in den betroffenen Sections auf `image_url` mit width-Param umstellen.
3. **hreflang `pt` vs `pt-PT`** (aus `output/blog_review/`): Shopify Markets-Sprache
   Portugiesisch auf Region PT prüfen — separat vom Canonical-Thema.

## 3. Reihenfolge zum Abarbeiten

1. Phase-1-Fixes deployen (sind mit diesem Branch gemergt aktiv — `run.sh` zieht `main`).
2. `python3 scripts/backfill_seo_cleanup.py --check-links` → Dry-Run-Report prüfen.
3. `python3 scripts/backfill_seo_cleanup.py --apply --fix-links` (legt vorher Backup an).
4. Theme-Punkte aus Abschnitt 2 im Shopify-Admin.
5. GSC „Behebung validieren" (s. `docs/GSC_CANONICAL_FIX.md`), nächsten Ahrefs-Crawl abwarten:
   erwartet ↓ Multiple H1, ↓ Links to redirect, keine **neuen** Meta-missing/Sitemap-Seiten,
   ↓ Missing alt (nach Theme-Fix).
