# Legal Guardrails for Comparison / Brand Blog Content (EU & German law)

> **Not legal advice.** This documents the *technical* guardrails the bot enforces
> so blog content stays defensible under EU/German advertising law. Have a lawyer
> review the live articles and this checklist. Enforcement lives in the generation
> prompt (`seo_bot.py` → `LEGAL COMPLIANCE` rules + `BRAND_FACTS`) and the quality
> gate (`briefs/quality_gate.py::check_compliance`), with a retrofit pass that
> scans existing articles.

## Why (the risk)

The content is a **manufacturer's own advertising** on velluto-shop.com. Automated
comparison articles that name competitors are the main exposure. Typical claimants:
competitors and the *Wettbewerbszentrale*; typical instrument: **Abmahnung** (costs
money). EU Omnibus fines can reach **4 % of annual turnover**.

## The rules the bot enforces

### 1. No fabricated tests, reviews or first-hand experience — §§ 5, 5a UWG + EU Omnibus
No real test/lab/trial was performed, so the content must never imply one.
**Blocked phrasings:** "we tested", "in our tests/lab", "hands-on", "field/road
test", "after N hours/km of testing", "Testsieger", "getestet", "editorial test",
star ratings, self-made test seals, "the evidence supports [our test]". Fake or
implied consumer reviews/tests are an explicitly banned practice under the EU
Omnibus Directive (2019/2161).

### 2. Separation requirement / no disguised editorial ad — § 5a UWG (Anhang Nr. 11)
It is brand content, not independent journalism. **Byline is "Velluto"** (not
"Velluto Redaktion"). No "independent review", "our lab", journalistic test framing.

### 3. Comparative advertising is allowed **only if** — § 6 Abs. 2 UWG
Naming competitors is legal (EU Dir. 2006/114/EG) **when** every statement about
them is:
- **Objective & verifiable** (a fact with a provable core, checkable by experts) —
  use only what the competitor **publishes officially**; never invent specs/prices.
- On **essential, relevant, typical** features or price (no cherry-picked trivia).
- **Not one-sided / not misleading** — don't omit context that flips the conclusion.
- **Current** — automation's weak spot: **no absolute "does not offer X / doesn't
  publish its weights / no trial"** claims that silently go stale into false
  statements. Describe Velluto's *own* strengths instead.
- **Not disparaging** (Nr. 5): no "degrades", "inferior", "cheap/flimsy", mockery,
  and no doubt-casting asymmetry like "UV400 (stated)" for a rival vs "certified"
  for Velluto, "only claims", "merely".
- **No confusion** (Nr. 3), **no reputation exploitation** (Nr. 4), **no imitation
  claim** (Nr. 6).

### 4. True claims about our own product — § 5 UWG
Only substantiated claims. Backed & allowed: **UV400 certified** (EN ISO 12312-1 /
PSA Reg. EU 2016/425 — keep the conformity docs on file), **25 g**, **anti-fog**.
Never invent other certifications, awards or seals. Note: sunglasses are PPE
(Category I); safety/UV claims must match the actual CE/EN ISO 12312-1 marking.

### 5. Correct origin — § 5 UWG
Velluto is a **German** brand with **Italian design**. Never "Dutch / Nederlands /
Netherlands". A false geographic origin is misleading.

## Where it's enforced

| Layer | File | What |
|---|---|---|
| Prevention (prompt) | `seo_bot.py` | `BRAND_FACTS` origin + `LEGAL COMPLIANCE` L1–L5 rules, byline "Velluto" |
| Prevention (gate) | `briefs/quality_gate.py` | `check_compliance()` blocks fake-test / disparagement / false-origin phrasings before publish |
| Cure (existing) | `content_retrofit.py` compliance pass | scans live articles → auto-softens mechanical issues, sets factual-risk articles to **draft** for review |
| Test | `tests/smoke_test_legal_compliance.py` | true/false-positive coverage |

## Sources (background reading, not exhaustive)

- § 6 UWG comparative advertising — [gesetze-im-internet.de](https://www.gesetze-im-internet.de/uwg_2004/__6.html), [ra-plutte.de](https://www.ra-plutte.de/vergleichende-werbung/), [IHK Frankfurt](https://www.frankfurt-main.ihk.de/recht/uebersicht-alle-rechtsthemen/wettbewerbsrecht/unlauterer-wettbewerb/vergleichende-werbung)
- Disguised advertising / Trennungsgebot § 5a UWG — [omsels.info](https://www.omsels.info/die-verbote-oder-was-darf-ich-nicht/3-5a-abs-6-uwg-verschleierung-des-kommerziellen-zwecks/agetarnte-werbung), [it-recht-kanzlei.de](https://www.it-recht-kanzlei.de/reaktionelle-werbung-trennung.html)
- Advertising with tests / test results — [ra-plutte.de](https://www.ra-plutte.de/werbung-mit-testergebnissen-uebersicht-tipps-beispiele/), [it-recht-kanzlei.de](https://www.it-recht-kanzlei.de/testergebnisse-uwg.html), [cmshs-bloggt.de](https://www.cmshs-bloggt.de/gewerblicher-rechtsschutz/wettbewerbsrecht-uwg/abenteuer-werbewildnis-werben-mit-selbst-durchgefuehrten-produkttests/)
- EU Omnibus / fake reviews — [EUR-Lex UCPD](https://eur-lex.europa.eu/DE/legal-content/summary/unfair-commercial-practices.html), [Händlerbund FAQ](https://www.haendlerbund.de/de/news/aktuelles/rechtliches/3219-faq-omnibus-richtlinie-zum-eu-verbraucherrecht)
- Sunglasses as PPE / UV claims — [TÜV-Verband](https://www.tuev-verband.de/pressemitteilungen/sonnenbrillen-was-die-augen-zuverlaessig-schuetzt), [hamburg.de Produktsicherheit](https://www.hamburg.de/politik-und-verwaltung/behoerden/bjv/themen/verbraucherschutz/produktsicherheit/sonnenbrillen-89058)
