#!/usr/bin/env python3
"""
Daily SEO/GEO report — emailed at the end of every run.sh.

Two jobs in one mail:
  1. Daily summary (always): what published, GSC clicks/impressions, ranking
     movement, GEO citation rate, today's optimisation focus, spend.
  2. Health / alert: if anything needs Leopold's attention (a failed pipeline
     step, dead Google/Pinterest creds, a blocked article, a failed push, …),
     the subject is flagged ⚠️ and an ACTION NEEDED block is put at the top.

Reads run.sh's outcome via env (RUN_FAILED newline-list, RUN_PUSH_OK) plus the
on-disk artifacts. Never raises — reporting must not break the pipeline.
"""
from __future__ import annotations

import datetime
import json
import os

import mailer

BASE  = os.path.dirname(os.path.abspath(__file__))
TODAY = datetime.date.today()
TODAY_S = TODAY.isoformat()
LOG_PATH = "/var/log/seo-bot.log"


def _load(path, default):
    try:
        with open(os.path.join(BASE, path), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _vis(day: dict) -> float:
    s = []
    for _, p in day.items():
        v = p.get("Velluto", 0)
        s.append(100.0 if 0 < v <= 3 else 70.0 if 0 < v <= 10 else 30.0 if 0 < v <= 20 else 0.0)
    return round(sum(s) / len(s), 1) if s else 0.0


def _current_run_log() -> str:
    """Return only the log of the CURRENT run (since the last '[SEO Bot] Starting'
    marker). The log is cumulative/append-only, so scanning the whole tail would
    keep re-flagging already-fixed errors from previous runs."""
    try:
        with open(LOG_PATH, encoding="utf-8", errors="ignore") as f:
            txt = "".join(f.readlines()[-3000:])
    except Exception:
        return ""
    idx = txt.rfind("[SEO Bot] Starting")
    return txt[idx:] if idx != -1 else txt


def build() -> tuple[str, str]:
    problems: list[str] = []   # ACTION NEEDED items
    notes:    list[str] = []   # FYI warnings

    # ── run.sh outcome (from env) ───────────────────────────────────────────
    failed_steps = [s for s in (os.getenv("RUN_FAILED", "").splitlines()) if s.strip()]
    push_ok = os.getenv("RUN_PUSH_OK", "true").lower() != "false"
    for s in failed_steps:
        problems.append(f"Pipeline-Schritt fehlgeschlagen: {s}")
    if not push_ok:
        problems.append("git push fehlgeschlagen — Änderungen NICHT auf GitHub gesichert (Auth/Deploy-Key prüfen).")

    # ── Published today ─────────────────────────────────────────────────────
    pub = _load("published_today.json", [])
    if isinstance(pub, dict):
        pub = pub.get("articles", []) if "articles" in pub else [pub]
    pub_titles = [p.get("title", "?") for p in pub] if isinstance(pub, list) else []
    if not pub_titles:
        notes.append("Heute wurde kein neuer Artikel veröffentlicht (evtl. Keyword-Pool leer oder Generierung fehlgeschlagen).")

    # ── GSC ─────────────────────────────────────────────────────────────────
    gsc = _load("gsc_data.json", {})
    trend = sorted(gsc.get("daily_trend", []), key=lambda r: r["keys"][0])[-30:]
    clicks30 = sum(r.get("clicks", 0) for r in trend)
    impr30   = sum(r.get("impressions", 0) for r in trend)
    last_row = trend[-1] if trend else {}
    pos_now  = last_row.get("position", 0)
    top_q    = sorted(gsc.get("top_queries", []), key=lambda r: r.get("clicks", 0), reverse=True)[:5]
    if not gsc or not gsc.get("top_queries"):
        problems.append("Google Search Console liefert keine Daten — Google-OAuth/Zugang prüfen (GOOGLE_* in .env).")
    elif gsc.get("date") != TODAY_S:
        notes.append(f"GSC-Daten sind von {gsc.get('date','?')}, nicht von heute (Google-Lag oder Abruf übersprungen).")

    # ── Rankings ────────────────────────────────────────────────────────────
    rh = _load("ranking_history.json", {})
    dates = sorted(rh)
    vis_now = _vis(rh.get(dates[-1], {})) if dates else 0.0
    past = str(TODAY - datetime.timedelta(days=7))
    vis_7d = _vis(rh.get(past, {})) if past in rh else None
    top10 = sum(1 for _, p in rh.get(dates[-1], {}).items() if 0 < p.get("Velluto", 0) <= 10) if dates else 0

    # ── GEO ─────────────────────────────────────────────────────────────────
    geo = _load("geo_performance.json", {})
    geo_rec = (geo.get("history", {}) or {}).get(geo.get("latest", ""), {})

    # ── Insights freshness + quality gate ───────────────────────────────────
    ins = _load("seo_insights.json", {})
    if ins.get("analysis_date") and ins["analysis_date"] != TODAY_S:
        notes.append(f"SEO-Analyse nicht heute aktualisiert (Stand {ins['analysis_date']}) — Claude-Analyse/Token prüfen.")
    qg = _load("output/quality_gate_failures.json", [])
    qg_today = [q for q in qg if isinstance(q, dict) and str(q.get("checked_at", "")).startswith(TODAY_S)] if isinstance(qg, list) else []
    if qg_today:
        notes.append(f"{len(qg_today)} Artikel hat/haben heute das Quality-Gate nicht bestanden (nicht veröffentlicht).")

    # ── Token cost ──────────────────────────────────────────────────────────
    usage = _load("token_usage.json", {})
    cost_today = (usage.get(TODAY_S, {}) or {}).get("cost_usd", 0.0)

    # ── log scan (CURRENT run only) for soft failures not surfaced as steps ──
    # git-auth/push is covered reliably by RUN_PUSH_OK above, so it's not re-scanned.
    log = _current_run_log()
    if "Pinterest error 401" in log or "boards:write" in log:
        problems.append("Pinterest-Posting schlägt fehl (401 / Token-Scope) — Token mit boards:write erneuern.")
    if "Analysis failed" in log and ins.get("analysis_date") != TODAY_S:
        problems.append("Claude-SEO-Analyse bricht ab (JSON/Token) — seo_insights wird nicht aktualisiert.")

    # ── compose ─────────────────────────────────────────────────────────────
    L = []
    if problems:
        L.append("⚠️  AKTION NÖTIG / RISIKEN")
        L += [f"   • {p}" for p in problems]
        L.append("")
    if notes:
        L.append("ℹ️  Hinweise")
        L += [f"   • {n}" for n in notes]
        L.append("")

    L.append("📝 HEUTE VERÖFFENTLICHT")
    if pub_titles:
        L += [f"   • {t}" for t in pub_titles]
    else:
        L.append("   • —")
    L.append("")

    L.append("📊 GOOGLE SEARCH CONSOLE (30 Tage, live)")
    L.append(f"   • Klicks: {clicks30}   |   Impressionen: {impr30:,}")
    L.append(f"   • Ø Position (letzter Tag): {pos_now:.1f}")
    if top_q:
        L.append("   • Top-Suchbegriffe (Klicks):")
        L += [f"       - {r['keys'][0]}: {r.get('clicks',0)} Klicks / {r.get('impressions',0)} Impr." for r in top_q]
    L.append("")

    L.append("📈 RANKINGS (eigene Messung)")
    delta = f"  ({'▲' if vis_now>=(vis_7d or 0) else '▼'} vs. 7 Tage: {vis_7d})" if vis_7d is not None else ""
    L.append(f"   • Visibility-Score: {vis_now}{delta}")
    L.append(f"   • Keywords in Top-10: {top10}")
    L.append("")

    L.append("🤖 GEO / KI-SICHTBARKEIT (Google AI Overviews)")
    if geo_rec.get("aio_serps"):
        L.append(f"   • Velluto-Citation-Rate: {geo_rec.get('velluto_citation_rate',0)}%  "
                 f"(Wettbewerber: {geo_rec.get('competitor_citation_rate',0)}%)")
        L.append(f"   • Owned-Citation-Share: {geo_rec.get('owned_citation_share',0)}%")
    else:
        L.append("   • Noch keine AI-Overview-Daten erfasst.")
    L.append("")

    if ins.get("our_gaps") or ins.get("seo_quick_wins"):
        L.append("🧠 HEUTIGER OPTIMIERUNGS-FOKUS")
        for g in (ins.get("seo_quick_wins") or [])[:2]:
            L.append(f"   • Quick-Win: {g}")
        for g in (ins.get("our_gaps") or [])[:2]:
            L.append(f"   • Lücke: {g}")
        L.append("")

    L.append(f"💶 KI-Kosten heute: ${cost_today:.4f}")
    L.append("")
    L.append("— Velluto SEO/GEO-Bot · Dashboard: https://leopold-cell.github.io/velluto-seo-bot/")

    body = "\n".join(L)
    flag = "⚠️ AKTION NÖTIG" if problems else "✅"
    subject = f"{flag} Velluto SEO/GEO Tagesreport — {TODAY_S}"
    return subject, body


def main():
    try:
        subject, body = build()
    except Exception as e:
        # Last-resort: even our own report failing is worth an alert.
        subject = f"⚠️ Velluto Tagesreport konnte nicht erstellt werden — {TODAY_S}"
        body = f"daily_report.py ist auf einen Fehler gelaufen:\n\n{e!r}\n\nBitte VPS/Logs prüfen."
    mailer.send_email(subject, body)


if __name__ == "__main__":
    main()
