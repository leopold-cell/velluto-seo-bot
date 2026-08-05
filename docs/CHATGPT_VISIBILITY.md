# ChatGPT-Sichtbarkeit — Ist-Zustand, Maßnahmen, manuelle Schritte

**Stand:** 2026-08-02 · **Ausgangspunkt:** 10-Schritte-Anleitung „Step-by-Step ChatGPT
Optimization Plan" · **Property:** `sc-domain:velluto-shop.com`

---

## 1. Die wichtigste Erkenntnis

Der **technische** Teil der Anleitung war bei Velluto schon erledigt, bevor dieses
Paket begann. Live geprüft am 2026-08-02:

- **robots.txt** blockt keinen KI-Crawler. `OAI-SearchBot`, `GPTBot`, `PerplexityBot`
  und `bingbot` bekommen auf einem Blog-Artikel jeweils **HTTP 200**.
- **Blog-Artikel** liefern Article + FAQPage (9 Q&A) + BreadcrumbList + Organization +
  ImageObject. 1× H1, 11× H2, alle 28 Bilder mit `alt`.
- **Produktseiten** liefern Product + Offer + AggregateRating + Review + Brand +
  FAQPage (7 Q&A) + MerchantReturnPolicy. (Der in `GSC_STRUCTURED_DATA_FIX.md`
  dokumentierte Doppel-`brand`/`aggregateRating`-Fehler ist live nicht mehr sichtbar.)

Gefehlt hat etwas anderes: **es gab keinen einzigen Messpunkt für ChatGPT**, keinen
Weg von „bei dieser Frage werden wir nicht zitiert" zurück in die Content-Planung,
und **null Off-Site-Aktivität** — obwohl die eigenen Daten des Bots Reddit als
wichtigsten unerschlossenen Hebel ausweisen.

### Wo die Anleitung nicht stimmt

- **„Bing powers ChatGPT"** — nur noch halb richtig. ChatGPT Search nutzt inzwischen
  einen eigenen Crawler (OAI-SearchBot) und Index. Bing Webmaster Tools bleibt
  sinnvoll, ist aber kein Schalter, der Sichtbarkeit herstellt.
- **Wikipedia** — für eine DTC-Marke dieser Größe unrealistisch (Relevanzkriterien),
  und ein Selbsteintrag verstößt gegen die Interessenkonflikt-Regeln. Gestrichen.
- **Brand GPT** — beeinflusst **nicht**, was ChatGPT normalen Nutzern antwortet.
  Reiner Marken-Touchpoint, niedrigste Priorität.

---

## 2. Was gebaut wurde

### `scripts/chatgpt_monitor.py` — der fehlende Messpunkt

Fragt dieselben Käuferfragen wie der Perplexity-Monitor über die OpenAI Responses API
mit `web_search` und protokolliert, ob velluto-shop.com als Quelle auftaucht.

- 4 Märkte (en/de/nl/fr), 7-Tage-Gate, schreibt `data/chatgpt_geo.json`
- **Zwei getrennte Metriken:** `cited` (echte Quellenangabe — das ist die Rate) und
  `mentioned` (Markenname im Text ohne Quell-Link). Der Perplexity-Monitor wirft
  beides zusammen (`perplexity_monitor.py`, `or "velluto" in text.lower()`) und
  **überschätzt seine Rate dadurch**. Beim Vergleich der Flächen die `cited`-Werte
  nebeneinanderlegen, nicht die Perplexity-Rate gegen die ChatGPT-Rate.
- **Einordnung:** Die API ist ein **Proxy** für chatgpt.com, nicht dieselbe
  Oberfläche. Den **Trend** lesen, nicht die absolute Zahl.
- **Kosten:** ~40 Web-Search-Calls/Woche, pro Tool-Call abgerechnet — realistisch
  **0,40–1,00 $/Woche**, nicht „ein paar Cent". Wird pro Lauf ausgegeben.
- Modell über `CHATGPT_MONITOR_MODEL` in der `.env` umstellbar.

**Vor dem ersten echten Lauf** einmal die Zitat-Struktur verifizieren:

```bash
python3 scripts/chatgpt_monitor.py --force --dry-run   # 1 Frage, zeigt die erkannten Domains
python3 scripts/chatgpt_monitor.py --force             # voller Lauf
```

**Fehlerbilder** — Konfigurationsfehler (toter Key, kein Guthaben, falsches Modell)
brechen sofort mit einer Klartext-Zeile ab, statt sich 40× zu wiederholen, und
schreiben **nichts** — eine falsche Baseline wäre schlimmer als gar keine:

| Meldung | Ursache |
|---|---|
| `OPENAI_API_KEY is rejected (401)` | Key widerrufen/abgelaufen → auf platform.openai.com erneuern |
| `OpenAI rate/quota limit (429)` | meist leeres Billing-Guthaben |
| `Model '…' is not available` | `CHATGPT_MONITOR_MODEL` in der `.env` setzen |

> Beim ersten Rollout (2026-08-03) war der OpenAI-Key in der VPS-`.env` bereits tot
> (401). Betroffen war nichts: `image_generator.py` ist der einzige weitere Nutzer,
> und die KI-Bildgenerierung steht in `config/publishing_rules.yml` ohnehin auf
> `generate: false`. Aufgefallen ist es erst, weil dieser Monitor der erste *aktive*
> Nutzer des Keys ist — deshalb prüft `resource_monitor.py` den Key jetzt täglich mit.

### `scripts/geo_gaps.py` — Messung zurück in den Content

Zieht aus `chatgpt_geo.json` + `perplexity_geo.json` die Fragen, bei denen Velluto
**über mehrere Läufe hinweg** nie zitiert wurde, und zeigt, wer stattdessen zitiert
wird. Erscheint im Wochen-Digest als Vorschlagsliste für `data/paa_seed.json`.

**Bewusst nicht automatisch.** Aus KI-Antworten geerntete Fragen betreffen regelmäßig
Dinge, die Velluto nicht verkauft (Photochrom, Polarisation, Sehstärke). Automatisch
eingespeist würden sie Briefs in Richtung Content schieben, den weder das Sortiment
noch das Legal-Gate tragen. Ein Mensch wählt aus — der Rest der Kette läuft dann
automatisch:

```
data/paa_seed.json → briefs/us_master_brief.py::_gather_paa_questions()
  → brief["must_answer_questions"] → wörtliche H2 + 40-70-Wörter-Antwort
  → ===FAQ_JSON=== → FAQPage-JSON-LD
```

### `scripts/reddit_drafts.py` — Off-Site, ohne Bann-Risiko

Erzeugt fertige Post-Entwürfe für die Fragen, bei denen die KI **Reddit statt Velluto**
zitiert — mit Ziel-Subreddit, Subreddit-Regel und passendem eigenen Artikel als Quelle.

- **Kein Auto-Posting.** `link_builder.py` hat seit jeher einen vollständigen
  Reddit-Poster, der nie gepostet hat (43× „no_credentials"). Das ist das richtige
  Ergebnis: ein frischer Account ohne Karma wird in r/cycling als Spam gebannt, und
  ein Bann ist dauerhaft.
- **Jeder Entwurf läuft durch `briefs/quality_gate.py::check_compliance()`.**
  Ein Reddit-Post ist nutzersichtbarer Werbetext — ein erfundenes „wir haben getestet"
  ist dort genauso ein UWG-Problem wie im Shop. Auffällige Entwürfe werden mit
  „⛔ NICHT POSTEN" plus Begründung ausgewiesen, nie stillschweigend geglättet.
- Verteilt Entwürfe über verschiedene Subreddits (zwei Posts/Woche im selben Sub
  sind ein Spam-Signal).

### Deutscher Markt nachgezogen

- `dashboard.py` `RANK_KEYWORDS` enthielt **0 deutsche Keywords** — DACH-Fortschritt
  war strukturell unsichtbar. Ergänzt: „beste Fahrradbrille 2026", „Fahrradbrille
  Test", „Rennradbrille Wechselgläser", „leichte Rennradbrille".
- `data/paa_seed.json` hatte für DE 4 Cluster gegen 10 für EN → auf 9 Cluster /
  37 Fragen erweitert. **`photochromic` bewusst ausgelassen** — Velluto bietet keine
  photochromen Gläser an; die Fragen dort würden Content erzwingen, den das Sortiment
  nicht deckt.

### Kleine technische Lücken

- **Titelbild-Alt** (`seo_bot.py::publish`): Das Theme rendert
  `alt="{{ article.image.alt }}"` — mangels `alt` am Shopify-Artikel kam
  `alt=""` heraus. Das prominenteste Bild jeder Artikelseite war für Screenreader
  und Crawler unsichtbar. Wird jetzt gesetzt.
- **`scripts/backfill_article_schema.py`** (neu): Der Altbestand hat FAQPage, aber
  kein Article-JSON-LD. Nutzt die **echten** `published_at`/`updated_at` aus Shopify
  statt „heute" — ein rückdatierter Artikel, der behauptet heute erschienen zu sein,
  ist ein schlechteres Signal als gar kein Datum.

### Nicht umgesetzt (bewusst)

- **Collection-Schema (ItemList/CollectionPage)** — fehlt live, aber Produkt- und
  Collection-Templates liegen nicht in diesem Repo (`.shopifyignore`). Theme-Eingriff,
  separat zu entscheiden.
- **Eigene `llms.txt`** — Shopify generiert `/llms.txt` und `/agents.md` selbst
  (beide live) und sie sind rein commerce-orientiert (UCP/MCP, Shop-Skill).
  Überschreiben ist nicht vorgesehen.

---

## 3. Manuelle Schritte

Diese vier lassen sich nicht per Code erledigen.

### 3.1 Bing Webmaster Tools — höchste Priorität

1. `bing.com/webmasters` → mit Microsoft-Konto anmelden
2. **„Import from Google Search Console"** — schnellster Weg, übernimmt Property und
   Verifizierung
3. Falls manuell: Property `velluto-shop.com` hinzufügen, per DNS-TXT verifizieren
4. Sitemap einreichen: `https://velluto-shop.com/sitemap.xml`
5. Nach ein paar Tagen unter **„Site Explorer"** prüfen, wie viele URLs indexiert sind

> Ein `site:`-Test per Skript ist **nicht** aussagekräftig — Bing liefert Bots eine
> JS-Hülle ohne Ergebnisse. Die belastbare Zahl steht nur in den Webmaster Tools.

**Optional danach — IndexNow:** ersetzt den im Juli entfernten, toten Sitemap-Ping.
Key unter Bing WMT → „IndexNow" erzeugen, als `<key>.txt` im Shop-Root hinterlegen.

### 3.2 OpenAI Product Discovery

1. `openai.com/chatgpt/search-product-discovery` öffnen
2. Formular mit Shop-Daten ausfüllen; als Produktfeed den vorhandenen
   Shopify-Feed angeben
3. Bestätigung abwarten — Aufnahme ist nicht garantiert und dauert

### 3.3 Reddit-Account

Reihenfolge ist entscheidend, sonst ist der Account verbrannt:

1. Account anlegen, **mehrere Wochen** nur kommentieren — echte Antworten in
   r/cycling, r/RoadCycling, r/bicycling. Keine Links, keine Markennennung.
2. Ab ~100 Kommentar-Karma: Beiträge ohne Link (Fragen, Erfahrungsberichte)
3. Erst danach die Entwürfe aus dem Wochen-Digest — und auch dann gilt: der Beitrag
   muss **ohne** den Link funktionieren, der Link kommt zuletzt oder auf Nachfrage
4. Nie zwei Beiträge pro Woche im selben Subreddit

### 3.4 Brand GPT

1. `chatgpt.com/gpts` → „Create"
2. Inhalte aus `BRAND_FACTS` (`seo_bot.py`) übernehmen: Specs, Preis ab 69 €,
   30-Tage-Rückgabe, was Velluto **nicht** anbietet
3. Veröffentlichen

> Ehrliche Erwartung: Das ändert **nichts** daran, was ChatGPT normalen Nutzern
> antwortet. Es ist ein Marken-Touchpoint, kein Sichtbarkeits-Hebel.

---

## 4. Reihenfolge

KI-Zitierraten bewegen sich über Wochen — deshalb zuerst messen, dann handeln.

1. **Baseline:** `chatgpt_monitor.py --force --dry-run`, dann voller Lauf
2. **Parallel:** Bing WMT + OpenAI-Formular (3.1, 3.2)
3. **Content:** Vorschläge aus `geo_gaps.py` prüfen und in `paa_seed.json` übernehmen
4. **Technik:** `backfill_article_schema.py --apply`
5. **Off-Site:** Reddit erst, wenn der Account warmgelaufen ist

---

## 5. Verifikation

```bash
# Messpunkt
python3 scripts/chatgpt_monitor.py --force --dry-run   # Zitat-Struktur prüfen
python3 scripts/chatgpt_monitor.py --force             # schreibt data/chatgpt_geo.json
python3 scripts/chatgpt_monitor.py                     # muss am 7-Tage-Gate abprallen

# Loop + Off-Site
python3 scripts/geo_gaps.py
python3 scripts/reddit_drafts.py --count 3

# Schema-Backfill
python3 scripts/backfill_article_schema.py             # Dry-Run
python3 scripts/backfill_article_schema.py --apply

# Titelbild-Alt: nach dem nächsten seo_bot-Lauf am Live-Artikel prüfen
curl -s <artikel-url> | grep -o '<img[^>]*hero[^>]*>' | head
```

**Vergleichswerte für in 4-6 Wochen** (Stand 2026-08-02):
Google AI Overviews **2,4 %** · Perplexity **10 %** (mit dem oben beschriebenen
Überschätzungs-Bias) · ChatGPT **noch nicht gemessen**.
