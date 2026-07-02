# Blueprint: „Giovanni" — Velluto AI-Company (autonome digitale Firma)

> **Deliverable:** Nur Architektur-Blueprint + phasierte Roadmap (keine Umsetzung).
> Die Weichen „Giovanni-Zugang", „Orchestrierung" und „Autonomie" sind hier als
> **empfohlene Defaults** gesetzt und bei der späteren Umsetzung anpassbar.

## Context

**Warum:** Aus den bestehenden Einzel-Automationen (SEO/GEO-Bot + Instagram-Reels)
soll eine **digitale Firma** werden: eine Org-Hierarchie aus Agents, in der Leopold
langfristig nur noch mit **„Giovanni" (digitaler CEO)** spricht, der Aufträge in die
Firma verteilt. Alles läuft remote auf einem/mehreren Servern; **N8N** liefert die
visuelle Übersicht über Aktivitäten & Workflows. Ziel: immer mehr Prozesse laufen
autonom durch Claude, mit Guardrails.

**Ausgangslage (viel existiert schon, wird wiederverwendet):** Das Repo
`velluto-seo-bot` (→ umbenennen zu `velluto-autopilot`) deckt bereits große Teile von
**Marketing (SEO/GEO)**, **Social (Instagram)**, **E-Commerce (Shopify)** und
**Reporting/Monitoring** ab. Diese Module werden zu den „Werkzeugen", die die
Abteilungs-Agents aufrufen — nicht neu gebaut.

**Empfohlene Defaults (bei Umsetzung bestätigen):**
- **Giovanni-Zugang:** Phase 1 über **Claude Code** (wie gewohnt), später **Telegram-Bot** (mobil).
- **Orchestrierung:** **Hybrid** — Claude = die „Gehirne" (Agents), N8N = Workflows,
  Konnektoren, Trigger, Freigabe-Gates & Übersicht.
- **Autonomie:** **autonom + Gates** — Freigabe nur bei nach-außen-gerichteten/
  irreversiblen Aktionen (Posts, Ads-Spend, Preis-/Shop-Änderungen, Zahlungen) und
  über Budget-Limits. QM + Prozessoptimierung laufen autonom.

---

## TEIL A — Das Org-Chart (die Firma)

```
                          Leopold  ⇄  GIOVANNI (CEO-Orchestrator)
                                          │
              ┌───────────────────────────┼───────── cross-cutting ──────────┐
              │                           │                                   │
        QM-Abteilung              Department Heads                    Prozessoptimierung
     (Input/Output-Qualität)   ┌────┬────┬────┬────┬────┬────┐     (Effizienz/Effektivität
      prüft & verbessert       │    │    │    │    │    │    │      der ganzen Firma)
                              MKT  SOCIAL SALES LOGI FIN  ECOM
                               │    │      │    │    │    │
                            Sub-Agents (granular, je Abteilung)
```

**Rollen & Verantwortung**
- **Giovanni (CEO):** einziger Kontaktpunkt. Nimmt Aufträge, zerlegt sie in
  **Programme → Arbeitsaufträge**, verteilt an Department Heads, aggregiert Status,
  berichtet zurück. Trifft keine Fachdetails selbst — delegiert.
- **Department Heads** (je Abteilung ein „Manager-Agent"):
  - **Marketing** — SEO, GEO, Google (Ads/GSC), Meta (Ads)
  - **Social Media** — Instagram, TikTok
  - **Vertrieb/Sales**
  - **Logistik/Supply-Chain**
  - **Finanzen/Controlling**
  - **E-Commerce-Management** — Shop-Überwachung, CRO, Produkt-/Content-Pflege
- **Sub-Agents:** granular, eine klar umrissene Aufgabe (Single-Responsibility), z. B.
  „Keyword-Research", „Artikel-Autor", „Reel-Produzent", „Shopify-Produkt-Anleger",
  „Ads-Budget-Optimierer".
- **QM-Abteilung** (über den Departments): prüft **Input & Output** aller Agents auf
  Qualität, gibt Verbesserungs-Feedback, blockt schlechten Output vor Außenaktionen.
- **Prozessoptimierung** (über den Departments): misst laufend Effizienz &
  Effektivität der Gesamtfirma (Durchlaufzeiten, Kosten/Token, Erfolgsquoten) und
  schlägt Prozess-/Prompt-/Tool-Verbesserungen vor.

**Kommunikationsregeln (technisch erzwungen, siehe Teil C)**
- **Vertikal erlaubt:** Sub-Agent ↔ Sub-Agent innerhalb derselben Abteilung, Sub-Agent ↔ eigener Head.
- **Horizontal nur über Heads:** cross-department läuft ausschließlich Head → Head
  (bei Bedarf via Giovanni). Kein Sub-Agent spricht direkt mit einer fremden Abteilung.
- **QM & Prozessopt.:** Lese-Zugriff auf alles (Beobachter) + Direktiven nach unten
  ausschließlich über die Heads.

---

## TEIL B — Aktueller Stand → Abteilungs-Mapping (reuse-first)

| Abteilung | Existierende Module (werden zu „Tools" der Agents) |
|---|---|
| **Marketing / SEO** | `seo_bot.py`, `seo_optimizer.py`, `keyword_research.py`, `research/*` (gsc_fetcher, serp_fetcher, ai_overview_monitor), `briefs/*`, `review/*`, `meta_optimizer.py`, `decision/topic_selector.py` |
| **Marketing / GEO** | `geo_monitor.py`, `research/ai_overview_monitor.py`, `geo_performance.json` |
| **Marketing / Meta+Google** | Meta-Ads-Env (`META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`) + GSC-OAuth vorhanden (noch auszubauen) |
| **Social Media** | `instagram_reel_brief.py`, `instagram_post.py`, `caption_video.py`, `higgsfield_*.py`, `drive_upload.py`, `run_reel.sh`; Pinterest/Reddit (`link_builder.py`) |
| **E-Commerce** | Shopify-Integration in `seo_bot.py` (GraphQL), `mint_shopify_token.py`, Translations |
| **Finanzen/Controlling** | `scripts/seo_sales_report.py`, `token_usage.json`, `dashboard.py` |
| **QM / Prozessopt. (Keime)** | `review/*` (quality_audit, ui_audit, seo_geo_audit), `resource_monitor.py`, `daily_report.py`, `blog_review.py` |
| **Infra/Ops (geteilt)** | `mailer.py`, `resource_monitor.py`, `run.sh` (step/FAILED/Secret-Guard), `.gitignore`-Guards |

→ **Vertrieb** und **Logistik/Supply-Chain** sind neu (noch keine Module).

---

## TEIL C — Technische Architektur (Hybrid)

**1. Agent-Runtime („die Gehirne") — Claude Agent SDK (Python-Service)**
- Jeder Agent = `{ Rollen-System-Prompt, erlaubte Tools (MCP), Memory-Scope,
  Output-Schema, Manager (Head), Budget-Cap }`.
- Eine **Org-Registry** (YAML/DB) definiert Hierarchie + Rechte. Giovanni & Heads sind
  „Manager-Agents" (zerlegen + delegieren), Sub-Agents sind „Worker-Agents".
- Supervisor-Loop: Auftrag → Head zerlegt → Sub-Agents arbeiten → Head aggregiert →
  QM-Review → Gate → Ausführung.

**2. Message-Bus & Kommunikations-Router**
- Zentraler Router erzwingt die Regeln aus Teil A (vertikal frei, horizontal nur
  Head→Head). Nachrichten sind typisiert (Auftrag, Ergebnis, Frage, Direktive) und
  werden **auditiert** (jede Agent-Aktion ins Log).

**3. Firmengedächtnis („Company Brain")**
- **Postgres** (strukturiert): Programme, Arbeitsaufträge, Freigaben, KPIs,
  Produktkatalog, Abteilungs-State.
- **Vektor-/Wissensspeicher**: Markenstimme, Produktinfos, Playbooks, vergangene
  Entscheidungen. Die heutigen JSON-State-Files (`*_state.json`, `token_usage.json`,
  `geo_performance.json`, …) werden schrittweise hierher migriert.

**4. N8N — Orchestrierung, Konnektoren, Gates, Übersicht**
- **Trigger/Scheduler** (löst Cron ab): startet Programme/Workflows zeitgesteuert.
- **Konnektoren:** Shopify, Meta Ads, Google (Ads/GSC), Gmail, Google Drive, TikTok, DataForSEO.
- **Human-in-the-Loop-Nodes** = die **Freigabe-Gates**.
- **Workflow-as-Tool:** Agents rufen N8N-Workflows als Werkzeuge auf; N8N ruft die
  Agent-Runtime per Webhook.
- **Visuelle Übersicht:** genau die „Aktivitäten/Workflows im Blick"-Ebene, die du willst.

**5. Control-Plane (Steuerung & Code)**
- **Arbeitsaufträge/Tickets:** Postgres-Tabelle + N8N-Views (Giovanni-Aufträge werden
  hier sicht- und nachverfolgbar).
- **Code-Änderungen:** weiterhin über **GitHub** (Agents öffnen PRs → CI → VPS zieht
  `main`) — das bewährte Branch-pro-Task-Modell bleibt.

**6. Guardrails**
- **Freigabe-Gates** (N8N HITL) für Außen-/irreversible/Spend-Aktionen.
- **Budget-Caps** je Abteilung (Token + Ad-Spend); harte Obergrenzen.
- Bestehende **Secret-Guards** (`.gitignore` + `run.sh`-Scan) + **`resource_monitor.py`**.
- **Dry-Run-Defaults** (wie `IG_AUTOPOST`), **Audit-Log** jeder Aktion, **QM-Review**
  vor Außenaktionen.

**7. Hosting**
- VPS mit **Docker Compose**: `n8n`, `postgres`, `redis` (Queue), `agent-runtime`,
  und die bestehende `autopilot`-Jobs. Später horizontal auf mehrere Server
  aufteilen (Abteilungen/Services auslagern). **Secrets** via Infisical/Doppler oder SOPS.

---

## TEIL D — End-to-End-Beispiel: Produkt-Launch „Velluto CoffeeRacer"

*Du zu Giovanni: „In 3 Monaten kommt CoffeeRacer (Lifestyle-Sonnenbrille). Sorge
dafür, dass Shop + Marketing bereit sind und schon jetzt Nachfrage aufgebaut wird."*

1. **Giovanni** legt ein **Programm „CoffeeRacer Launch"** an (Zeithorizont 3 Monate),
   zerlegt in Arbeitsaufträge, verteilt an Heads.
2. **Marketing-Head** → Sub-Agents: Keyword-/GEO-Recherche „CoffeeRacer/Lifestyle
   Sonnenbrille", Pre-Launch-Artikelserie (SEO), GEO-Seeding, Meta/Google-Teaser-Plan
   (Entwurf, kein Spend ohne Gate).
3. **E-Commerce-Head** → Shopify-**Produkt-Draft** (unveröffentlicht), Landingpage-
   Entwurf, Übersetzungen, Collection-Struktur.
4. **Social-Head** → Reel-/TikTok-Teaser-Serie über 12 Wochen (Trial-Reels).
5. **Logistik-Head** → Verfügbarkeits-/Timing-Checkliste, „Ware da?"-Trigger.
6. **Finanzen-Head** → Umsatz-/Kosten-Forecast, Budget-Vorschläge.
7. **QM** prüft alle Outputs (Faktentreue, Markenstimme, Richtlinien); **Prozessopt.**
   misst Durchlauf/Kosten. **Gates** verlangen deine Freigabe für: Live-Schaltung von
   Content, Ads-Spend, Produkt-Publish, Preise.
8. **N8N** zeigt den ganzen Programm-Fortschritt; **Giovanni** meldet dir kompakte
   Status-Updates & offene Freigaben. Am Launch-Tag ist alles vorbereitet und wird
   (nach Freigabe) live geschaltet.

Dieses Szenario ist der **Akzeptanztest** der Architektur (siehe Verifizierung).

---

## TEIL E — Phasierte Roadmap

- **Phase 0 — Fundament:** Repo → `velluto-autopilot`; geteiltes `ops`-Package
  (mailer, resource_monitor, secret-guard, deploy); Docker Compose auf VPS; N8N +
  Postgres + Secrets-Manager aufsetzen.
- **Phase 1 — Giovanni + 2 Abteilungen:** Agent-Runtime + Giovanni + Marketing-Head +
  Social-Head, angebunden an bestehende Module als Tools; N8N-Workflows für deren
  Zeitpläne + Freigabe-Gates; CoffeeRacer-Flow als erstes Programm. Giovanni via Claude Code.
- **Phase 2 — E-Commerce + Finanzen:** Shop-Überwachung/CRO-Agents; Controlling-
  Reporting (teils vorhanden) in die Firma integrieren.
- **Phase 3 — Vertrieb + Logistik/Supply-Chain:** neue Abteilungen + Konnektoren.
- **Phase 4 — QM + Prozessoptimierung** als aktive, cross-cutting Agents (nicht nur Reviews).
- **Phase 5 — Skalierung:** Giovanni via Telegram; Multi-Server; optionales Web-Dashboard.

---

## TEIL F — Tech-Stack & neue Komponenten (für spätere Phasen)

**Stack:** Python + **Claude Agent SDK** (Agents) · **N8N** (Orchestrierung/Konnektoren/
Gates/Übersicht) · **Postgres** (+ Vektorspeicher) · **Redis** (Queue) · **Docker
Compose** (VPS) · **GitHub** (Code-Control-Plane) · **Infisical/Doppler** (Secrets).

**Neu zu bauen (Phase 0/1):**
- `ops/` geteiltes Package (mailer, resource_monitor, secret-guard, deploy-Helper).
- **Agent-Runtime-Service** mit Org-Registry (Rollen, Rechte, Budgets) + Message-Router.
- **N8N**-Compose + erste Workflows (Marketing- & Social-Zeitpläne, Freigabe-Gates).
- **Company-DB-Schema** (departments, agents, programs, work_orders, approvals, memory, audit_log).
- **Giovanni-Entrypoint** (Claude-Code-Skill/Session, die mit der Runtime spricht).

**Kritische bestehende Dateien (Wiederverwendung/Umbenennung):**
`run.sh`, `run_reel.sh`, `seo_bot.py`, `seo_optimizer.py`, `geo_monitor.py`,
`research/*`, `briefs/*`, `review/*`, `instagram_*.py`, `caption_video.py`,
`drive_upload.py`, `dashboard.py`, `daily_report.py`, `resource_monitor.py`,
`mailer.py`, `mint_shopify_token.py`.

---

## TEIL G — Risiken & Gegenmaßnahmen

- **Over-Engineering / Kosten (HOCH):** viele Agent-Calls = Token-Kosten. → klein
  starten (Phase 1: 2 Abteilungen), Budget-Caps, günstige Modelle für Routine (Haiku),
  teure nur für Kern-Entscheidungen.
- **Autonomie-Blast-Radius (HOCH):** je mehr autonom, desto größer der Schaden bei
  Fehlern. → Gates für Außenaktionen, Audit-Log, QM-Review, Dry-Run-Defaults.
- **Secret-Sprawl über viele Services (HOCH, nach den Leaks):** → Secrets-Manager,
  keine `.env`-Kopien, bestehende Guards behalten.
- **Halluzinationen/Marken-/Rechtsrisiko:** → QM als Pflicht-Review vor Publish; nur
  reale Fakten; keine fingierten Signale (wie schon im GEO-Plan verankert).
- **Kopplung N8N ↔ Agent-Runtime:** klare Schnittstellen (Webhook + Tool-Contracts),
  damit beide unabhängig deploybar bleiben.

---

## Verifizierung (Akzeptanzkriterien der späteren Umsetzung)

1. **Org-Regeln:** ein Sub-Agent kann eine fremde Abteilung nur über die Heads
   erreichen (Router lehnt Direkt-Nachrichten ab) — per Test nachweisbar.
2. **CoffeeRacer-Durchlauf:** Giovanni in einer Claude-Code-Session zerlegt den
   Auftrag, verteilt an Heads, Sub-Agents liefern Entwürfe, QM reviewt, **keine
   Außenaktion ohne Gate**, N8N zeigt den Fortschritt, Giovanni berichtet Status.
3. **Guardrails:** Post/Ad/Shop-Änderung wird ohne Freigabe **blockiert**; Budget-Cap
   greift; jede Aktion steht im Audit-Log.
4. **Reuse:** Marketing/Social/E-Commerce-Agents rufen die bestehenden Module auf
   (kein Neubau vorhandener Funktionen).

## Deployment
Alles remote auf dem VPS (Docker Compose). Code weiter über GitHub (`main` → VPS pull).
Dieser Blueprint ist ein **Design-Dokument** — die Umsetzung startet erst nach deiner
Freigabe der jeweiligen Phase.
