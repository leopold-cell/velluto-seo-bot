"""
Velluto SEO — 28-day blog review + site SEO/GEO audit package.

Sub-modules (all importable without live credentials; network/LLM calls are
guarded so `blog_review.py --dry-run` works offline):

  inventory          — fetch all bot-published blog articles
  quality_audit      — per-article quality checks (reuses briefs/quality_gate.py) + LLM score
  performance_audit  — per-article GSC performance (reuses research/gsc_fetcher.py)
  translation_audit  — translation completeness + correctness (reuses retrofit_translations.py)
  ui_audit           — Playwright screenshots + Claude vision (mobile + desktop)
  seo_geo_audit      — site-wide technical SEO + GEO (generative-engine) audit
  report             — aggregate findings → JSON + Markdown + email summary
  whatsapp           — deliver() via shared Gmail mailer (email only)

Orchestrated by top-level blog_review.py (runs every 28 days via a code gate).
"""
