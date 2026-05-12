#!/usr/bin/env python3
"""
Velluto SEO Dashboard — Sistrix-style, auto-generated daily via GitHub Actions.
"""

import os, json, datetime, requests, re, time
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID       = os.getenv("BLOG_ID", "127785959765")
HEADERS       = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

BASE    = os.path.dirname(os.path.abspath(__file__))
USAGE_LOG   = os.path.join(BASE, "token_usage.json")
TOPIC_LOG   = os.path.join(BASE, "topics_used.json")
DYNAMIC_LOG = os.path.join(BASE, "topics_dynamic.json")
RANKING_LOG = os.path.join(BASE, "ranking_history.json")

# ── Topic pools (mirrored from seo_bot.py) ───────────────────────────────────
TOPIC_POOL = [
    "why UV400 protection matters for road cyclists",
    "lens categories 0-3 explained for road cyclists",
    "high contrast lenses for cycling — when you need them",
    "clear lens cycling glasses — when and why to use them",
    "how anti-fog coating works on cycling glasses",
    "VellutoVisione high contrast lens review for road cyclists",
    "transparent cycling lens vs tinted lens — complete guide",
    "UV400 vs UV380 cycling glasses — what is the difference",
    "how anti-fog cycling glasses work — what to look for",
    "how to prevent cycling glasses from fogging on cold climbs",
    "cycling glasses for wind and rain — what to look for",
    "cycling glasses for low light and overcast Dutch weather",
    "best cycling glasses for autumn rides in the Netherlands",
    "winter cycling glasses guide — what to look for",
    "cycling glasses for early morning rides — low light tips",
    "cycling glasses fit guide — adjustable nose pads and frame sizing",
    "how to choose cycling glasses for your face shape",
    "why lightweight cycling glasses matter on long rides",
    "cycling glasses that don't slip — what to look for",
    "cycling glasses for small faces — fit guide 2026",
    "best cycling glasses for long distance sportives",
    "cycling glasses for narrow faces — a buyers guide",
    "interchangeable lens cycling glasses — are they worth it",
    "how to swap cycling glass lenses in under 10 seconds",
    "best interchangeable lens cycling glasses 2026",
    "click-in lens system cycling glasses — what to look for",
    "cycling glasses with two lenses — complete buying guide",
    "gravel cycling glasses vs road cycling glasses — key differences",
    "how cycling glasses protect against insects, debris and UV",
    "best cycling glasses for long climbs with changing light",
    "cycling glasses for the Giro d'Italia — what the pros use",
    "best cycling glasses for the Tour de France stage conditions",
    "cycling glasses for criteriums — speed and clarity",
    "cycling glasses for gran fondos — the complete guide",
    "road cycling glasses for beginners — what you need to know",
    "the best cycling glasses under €150 in 2026",
    "cycling glasses under €100 — worth it or not",
    "what makes road cycling glasses different from regular sunglasses",
    "cycling eye protection — why glasses are non-negotiable equipment",
    "how to clean cycling glasses properly without scratching lenses",
    "best cycling glasses for wide heads 2026",
    "cycling glasses buying guide — 10 things to check",
    "cycling glasses vs ski goggles — key differences explained",
    "de beste wielrenbril van 2026 — koopgids",
    "wielrenbril met verwisselbare glazen — wat je moet weten",
    "anti-condens wielrenbril — hoe werkt het",
    "wielrenbril voor brede gezichten — pasgids",
    "sportbril voor wielrennen — UV bescherming uitgelegd",
    "wielrenbril voor slechte weersomstandigheden — Nederland",
    "beste wielrenbril onder 150 euro in 2026",
    "wielrenbril voor de Amstel Gold Race — wat te kiezen",
    "POC cycling glasses vs budget alternatives — honest comparison",
    "Oakley cycling glasses — are premium brands worth the price",
    "cycling glasses brands compared — what to look for in 2026",
    "why expensive cycling glasses are not always better",
    "cycling glasses for spring classics — Ronde van Vlaanderen tips",
    "best cycling glasses for summer heat and bright sun",
    "cycling glasses gift guide for road cyclists 2026",
    "new cycling glasses for the new season — what changed in 2026",
]

COMPETITORS = {
    "Velluto":      "velluto-shop.com",
    "POC":          "pocbike.com",
    "Blitz":        "blitzeyewear.com",
    "Oakley":       "oakley.com",
    "Rapha":        "rapha.cc",
    "Rudy Project": "rudyproject.com",
    "Evil Eye":     "evil-eye.com",
}

COMP_COLORS = {
    "Velluto":      "#1d4ed8",
    "POC":          "#dc2626",
    "Blitz":        "#d97706",
    "Oakley":       "#7c3aed",
    "Rapha":        "#db2777",
    "Rudy Project": "#059669",
    "Evil Eye":     "#0891b2",
}

RANK_KEYWORDS = [
    "cycling glasses",
    "wielrenbril",
    "road cycling glasses",
    "best cycling glasses 2026",
    "cycling sunglasses",
    "wielrenbril kopen",
    "anti-fog cycling glasses",
    "UV400 cycling glasses",
    "interchangeable lens cycling glasses",
    "sportbril fietsen",
    "cycling glasses review",
    "lightweight cycling glasses",
    "best wielrenbril 2026",
    "cycling glasses under 150",
    "cycling glasses adjustable nose pads",
]


# ── Data fetchers ─────────────────────────────────────────────────────────────

def get_articles(limit=100):
    r = requests.get(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        f"?limit={limit}&fields=id,title,created_at,tags,handle",
        headers=HEADERS, timeout=15)
    return r.json().get("articles", [])


def get_usage():
    return json.load(open(USAGE_LOG)) if os.path.exists(USAGE_LOG) else {}


def get_used_topics():
    return json.load(open(TOPIC_LOG)) if os.path.exists(TOPIC_LOG) else []


def get_dynamic_topics():
    return json.load(open(DYNAMIC_LOG)) if os.path.exists(DYNAMIC_LOG) else []


def load_ranking_history():
    return json.load(open(RANKING_LOG)) if os.path.exists(RANKING_LOG) else {}


def save_ranking_history(h):
    json.dump(h, open(RANKING_LOG, "w"), indent=2)


def check_rankings():
    today   = str(datetime.date.today())
    history = load_ranking_history()
    if today in history:
        print("   Rankings cached for today.")
        return history
    today_data = {}
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            for kw in RANK_KEYWORDS:
                print(f"   → '{kw}'")
                try:
                    hits = list(ddgs.text(kw, max_results=20))
                except Exception:
                    hits = []
                positions = {}
                for name, domain in COMPETITORS.items():
                    pos = 0
                    for i, h in enumerate(hits, 1):
                        if domain in (h.get("href","") + h.get("body","")).lower():
                            pos = i; break
                    positions[name] = pos
                today_data[kw] = positions
                time.sleep(1.5)
    except Exception as e:
        print(f"   ✗ Rankings failed: {e}")
        today_data = {kw: {n: 0 for n in COMPETITORS} for kw in RANK_KEYWORDS}
    history[today] = today_data
    save_ranking_history(history)
    return history


def check_geo():
    queries = [
        "best cycling glasses 2026",
        "wielrenbril kopen",
        "Velluto cycling glasses review",
        "StradaPro cycling glasses",
        "beste wielrenbril 2026",
    ]
    results = []
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            for q in queries:
                try:
                    hits = list(ddgs.text(q, max_results=5))
                except Exception:
                    hits = []
                found = any("velluto" in (h.get("href","") + h.get("body","")).lower() for h in hits)
                results.append({"query": q, "found": found})
    except Exception:
        results = [{"query": q, "found": False} for q in queries]
    return results


# ── Analytics helpers ─────────────────────────────────────────────────────────

def visibility_score(ranking_history: dict, date_str: str) -> float:
    """Aggregate visibility % for Velluto on a given date (0–100)."""
    day = ranking_history.get(date_str, {})
    if not day: return 0.0
    scores = []
    for kw, positions in day.items():
        pos = positions.get("Velluto", 0)
        if pos == 0:   scores.append(0.0)
        elif pos <= 3:  scores.append(100.0)
        elif pos <= 10: scores.append(70.0)
        elif pos <= 20: scores.append(30.0)
        else:          scores.append(0.0)
    return round(sum(scores) / len(scores), 1) if scores else 0.0


def pos_delta(history: dict, kw: str, days: int) -> int | None:
    """Position change over N days. Positive = improved (moved up)."""
    today     = datetime.date.today()
    today_str = str(today)
    past_str  = str(today - datetime.timedelta(days=days))
    cur  = history.get(today_str, {}).get(kw, {}).get("Velluto", 0)
    past = history.get(past_str,  {}).get(kw, {}).get("Velluto", 0)
    if cur == 0 or past == 0: return None
    return past - cur  # positive = moved closer to #1


def delta_badge(d: int | None) -> str:
    if d is None: return '<span class="delta-none">—</span>'
    if d > 0:  return f'<span class="delta-up">▲{d}</span>'
    if d < 0:  return f'<span class="delta-down">▼{abs(d)}</span>'
    return '<span class="delta-flat">●0</span>'


def pos_badge(pos: int) -> str:
    if pos == 0:
        return '<span class="pos-none">—</span>'
    if pos <= 3:
        return f'<span class="pos-top3">#{pos}</span>'
    if pos <= 10:
        return f'<span class="pos-top10">#{pos}</span>'
    if pos <= 20:
        return f'<span class="pos-top20">#{pos}</span>'
    return f'<span class="pos-none">#{pos}</span>'


def kw_sparkline(history: dict, kw: str, days=14) -> str:
    today  = datetime.date.today()
    dates  = [(today - datetime.timedelta(days=i)).isoformat() for i in range(days-1, -1, -1)]
    points = [history.get(d, {}).get(kw, {}).get("Velluto", 0) for d in dates]
    # Convert: 0=not found shown as 25, else invert so 1=best
    def y(p): return 24 if p == 0 else min(p, 20)
    w, h = 80, 24
    if all(p == 0 for p in points):
        return f'<svg width="{w}" height="{h}"><line x1="0" y1="{h//2}" x2="{w}" y2="{h//2}" stroke="#e2e8f0" stroke-width="1.5"/></svg>'
    pts = []
    for i, p in enumerate(points):
        x = i * w / max(len(points)-1, 1)
        yv = y(p) / 25 * (h - 4) + 2
        pts.append(f"{x:.1f},{yv:.1f}")
    stroke = "#1d4ed8"
    return (f'<svg width="{w}" height="{h}">'
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{stroke}" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
            f'</svg>')


# ── Next scheduled posts ──────────────────────────────────────────────────────

def get_next_topics(n=10) -> list[dict]:
    used    = get_used_topics()
    dynamic = get_dynamic_topics()
    full    = list(dict.fromkeys(TOPIC_POOL + dynamic))
    queue   = [t for t in full if t not in used]
    today   = datetime.date.today()
    # 3 posts/day, so post n is today + n//3 days
    result  = []
    for i, t in enumerate(queue[:n]):
        day_offset = i // 3
        est_date   = today + datetime.timedelta(days=day_offset)
        result.append({"topic": t, "date": est_date.strftime("%d %b"), "dynamic": t in dynamic})
    return result


# ── HTML build ────────────────────────────────────────────────────────────────

def build_html(articles, usage, geo, ranking_history):
    today     = datetime.date.today()
    today_str = str(today)
    now       = datetime.datetime.now().strftime("%d %b %Y %H:%M")
    used_topics  = get_used_topics()
    dynamic_pool = get_dynamic_topics()
    full_pool    = list(dict.fromkeys(TOPIC_POOL + dynamic_pool))

    # ── Headline stats ──
    total_posts   = len(articles)
    posts_7d      = sum(1 for a in articles if a["created_at"][:10] >= str(today - datetime.timedelta(days=7)))
    total_cost    = sum(v["cost_usd"] for v in usage.values())
    cost_7d       = sum(v["cost_usd"] for k, v in usage.items()
                        if datetime.date.fromisoformat(k) >= today - datetime.timedelta(days=7))
    topics_done   = len(used_topics)
    topics_left   = len([t for t in full_pool if t not in used_topics])
    geo_score     = sum(1 for g in geo if g["found"])
    geo_pct       = int(geo_score / max(len(geo), 1) * 100)
    vis_today     = visibility_score(ranking_history, today_str)
    vis_7d_ago    = visibility_score(ranking_history, str(today - datetime.timedelta(days=7)))
    vis_delta     = round(vis_today - vis_7d_ago, 1)

    # ── Visibility trend (60 days) ──
    vis_dates  = [(today - datetime.timedelta(days=i)).isoformat() for i in range(59, -1, -1)]
    vis_scores = [visibility_score(ranking_history, d) for d in vis_dates]
    vis_labels = [d[5:] for d in vis_dates]

    # ── Cost chart (30 days) ──
    cost_dates  = [(today - datetime.timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    cost_values = [round(usage.get(d, {}).get("cost_usd", 0), 4) for d in cost_dates]
    cost_labels = [d[5:] for d in cost_dates]

    # ── Competitor visibility chart (30 days) ──
    comp_dates = [(today - datetime.timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    comp_labels = [d[5:] for d in comp_dates]
    comp_datasets = []
    for name, color in COMP_COLORS.items():
        data = []
        for d in comp_dates:
            day = ranking_history.get(d, {})
            if not day:
                data.append(None); continue
            scores = []
            for kw, positions in day.items():
                pos = positions.get(name, 0)
                if pos == 0:   scores.append(0)
                elif pos <= 3:  scores.append(100)
                elif pos <= 10: scores.append(70)
                elif pos <= 20: scores.append(30)
                else:          scores.append(0)
            data.append(round(sum(scores)/len(scores), 1) if scores else None)
        comp_datasets.append({
            "label": name, "data": data,
            "borderColor": color, "backgroundColor": color,
            "borderWidth": 3 if name == "Velluto" else 1.5,
            "tension": 0.3, "pointRadius": 2, "spanGaps": True,
        })

    # ── Keyword table ──
    today_rankings = ranking_history.get(today_str, {})
    kw_rows = ""
    for kw in RANK_KEYWORDS:
        pos    = today_rankings.get(kw, {}).get("Velluto", 0)
        d3     = pos_delta(ranking_history, kw, 3)
        d7     = pos_delta(ranking_history, kw, 7)
        d30    = pos_delta(ranking_history, kw, 30)
        d60    = pos_delta(ranking_history, kw, 60)
        spark  = kw_sparkline(ranking_history, kw)
        # Competitor mini badges
        comp_cells = ""
        for name in list(COMPETITORS.keys())[1:]:  # skip Velluto
            cp = today_rankings.get(kw, {}).get(name, 0)
            comp_cells += f'<td class="td-center">{pos_badge(cp)}</td>'
        kw_rows += f"""<tr>
          <td class="td-kw">{kw}</td>
          <td class="td-center">{pos_badge(pos)}</td>
          <td class="td-center">{delta_badge(d3)}</td>
          <td class="td-center">{delta_badge(d7)}</td>
          <td class="td-center">{delta_badge(d30)}</td>
          <td class="td-center">{delta_badge(d60)}</td>
          <td class="td-spark">{spark}</td>
          {comp_cells}
        </tr>"""

    comp_ths = "".join(
        f'<th style="color:{COMP_COLORS[n]}">{n}</th>'
        for n in list(COMPETITORS.keys())[1:]
    )

    # ── Next 10 posts ──
    next_topics = get_next_topics(10)
    next_rows = ""
    for i, t in enumerate(next_topics):
        tag = '<span class="badge-dyn">AI</span>' if t["dynamic"] else ""
        next_rows += f"""<tr>
          <td class="td-num">{i+1}</td>
          <td class="td-kw">{t['topic']} {tag}</td>
          <td class="td-center" style="color:#64748b">{t['date']}</td>
        </tr>"""

    # ── Recent posts ──
    post_rows = ""
    for a in articles[:20]:
        date = a["created_at"][:10]
        age  = (today - datetime.date.fromisoformat(date)).days
        tags = a.get("tags","").split(",")[0].strip() if a.get("tags") else "—"
        age_col = "#16a34a" if age <= 1 else "#64748b"
        post_rows += f"""<tr>
          <td class="td-kw">{a['title']}</td>
          <td class="td-center" style="color:#64748b;font-size:12px">{date}</td>
          <td class="td-center" style="color:{age_col};font-size:12px">{age}d ago</td>
          <td style="font-size:11px;color:#94a3b8;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{tags}</td>
        </tr>"""

    # ── GEO rows ──
    geo_rows = ""
    for g in geo:
        icon  = "✓" if g["found"] else "✗"
        color = "#16a34a" if g["found"] else "#dc2626"
        geo_rows += f'<tr><td class="td-kw">{g["query"]}</td><td class="td-center" style="color:{color};font-weight:700">{icon}</td></tr>'

    vis_arrow = "▲" if vis_delta >= 0 else "▼"
    vis_color = "#16a34a" if vis_delta >= 0 else "#dc2626"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Velluto SEO Intelligence</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif;background:#f1f5f9;color:#0f172a;font-size:14px}}
/* Top bar */
.topbar{{background:#0f172a;color:#fff;padding:0 24px;height:52px;display:flex;align-items:center;justify-content:space-between;gap:16px}}
.topbar .brand{{font-size:15px;font-weight:700;letter-spacing:.3px;display:flex;align-items:center;gap:10px}}
.topbar .brand span{{background:#1d4ed8;padding:3px 10px;border-radius:4px;font-size:12px}}
.topbar .meta{{font-size:11px;opacity:.5}}
/* Layout */
.wrap{{max-width:1400px;margin:0 auto;padding:20px 24px}}
.section-title{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:#64748b;margin:0 0 10px}}
/* KPI strip */
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}}
.kpi{{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:16px 18px}}
.kpi .label{{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px}}
.kpi .val{{font-size:28px;font-weight:800;color:#0f172a;line-height:1}}
.kpi .sub{{font-size:11px;color:#94a3b8;margin-top:4px}}
.kpi.accent{{border-left:3px solid #1d4ed8}}
/* Charts */
.chart-grid{{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-bottom:20px}}
.chart-card{{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:18px}}
.chart-card h3{{font-size:12px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.6px;margin-bottom:14px}}
/* Tables */
.table-card{{background:#fff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;margin-bottom:20px}}
.table-card .table-header{{padding:14px 16px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center}}
.table-card .table-header h3{{font-size:12px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.6px}}
table{{width:100%;border-collapse:collapse}}
th{{background:#f8fafc;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;padding:9px 12px;text-align:left;font-weight:600;border-bottom:1px solid #e2e8f0}}
td{{padding:9px 12px;border-bottom:1px solid #f8fafc;vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#f8fafc}}
.td-kw{{font-size:13px;color:#1e293b;font-weight:500;max-width:260px}}
.td-center{{text-align:center}}
.td-spark{{text-align:center;width:90px}}
.td-num{{text-align:center;color:#94a3b8;font-size:12px;width:32px}}
/* Position badges */
.pos-top3{{background:#dcfce7;color:#15803d;padding:2px 8px;border-radius:4px;font-weight:700;font-size:12px}}
.pos-top10{{background:#fef9c3;color:#854d0e;padding:2px 8px;border-radius:4px;font-weight:600;font-size:12px}}
.pos-top20{{background:#ffedd5;color:#9a3412;padding:2px 8px;border-radius:4px;font-size:12px}}
.pos-none{{color:#cbd5e1;font-size:12px}}
/* Delta badges */
.delta-up{{color:#16a34a;font-weight:700;font-size:12px}}
.delta-down{{color:#dc2626;font-weight:700;font-size:12px}}
.delta-flat{{color:#94a3b8;font-size:12px}}
.delta-none{{color:#e2e8f0;font-size:12px}}
/* Misc */
.badge-dyn{{background:#ede9fe;color:#6d28d9;font-size:10px;font-weight:700;padding:1px 6px;border-radius:3px;margin-left:6px}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}}
@media(max-width:900px){{.chart-grid,.two-col{{grid-template-columns:1fr}}}}
footer{{text-align:center;padding:24px;font-size:11px;color:#94a3b8}}
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    🚴 Velluto SEO Intelligence
    <span>velluto-shop.com</span>
  </div>
  <div class="meta">Updated {now} · auto-refreshes daily at 06:00 UTC</div>
</div>

<div class="wrap">

<!-- KPI strip -->
<div style="margin-bottom:8px;margin-top:4px" class="section-title">Overview</div>
<div class="kpi-grid">
  <div class="kpi accent">
    <div class="label">SEO Visibility</div>
    <div class="val">{vis_today:.0f}%</div>
    <div class="sub" style="color:{vis_color}">{vis_arrow} {abs(vis_delta):.1f}% vs 7 days ago</div>
  </div>
  <div class="kpi">
    <div class="label">Keywords Tracked</div>
    <div class="val">{len(RANK_KEYWORDS)}</div>
    <div class="sub">across EN + NL market</div>
  </div>
  <div class="kpi">
    <div class="label">GEO Mentions</div>
    <div class="val">{geo_score}/{len(geo)}</div>
    <div class="sub">{geo_pct}% of queries find Velluto</div>
  </div>
  <div class="kpi">
    <div class="label">Blog Posts</div>
    <div class="val">{total_posts}</div>
    <div class="sub">{posts_7d} published last 7 days</div>
  </div>
  <div class="kpi">
    <div class="label">Topic Pipeline</div>
    <div class="val">{topics_left}</div>
    <div class="sub">{topics_done} published · {len(dynamic_pool)} AI-discovered</div>
  </div>
  <div class="kpi">
    <div class="label">API Cost (7d)</div>
    <div class="val">${cost_7d:.2f}</div>
    <div class="sub">total ${total_cost:.2f} since launch</div>
  </div>
</div>

<!-- Visibility + Competitor charts -->
<div class="chart-grid">
  <div class="chart-card">
    <h3>SEO Visibility Index — Velluto vs Competitors (30 days)</h3>
    <canvas id="compChart" height="90"></canvas>
  </div>
  <div class="chart-card">
    <h3>Velluto Visibility Trend (60 days)</h3>
    <canvas id="visChart" height="90"></canvas>
  </div>
</div>

<!-- Keyword rankings table -->
<div class="table-card">
  <div class="table-header">
    <h3>Keyword Rankings — {today_str}</h3>
    <span style="font-size:11px;color:#94a3b8">Position in DuckDuckGo top 20 · Δ = position change (▲ = improved)</span>
  </div>
  <div style="overflow-x:auto">
    <table>
      <thead><tr>
        <th>Keyword</th>
        <th class="td-center">Position</th>
        <th class="td-center">Δ 3d</th>
        <th class="td-center">Δ 7d</th>
        <th class="td-center">Δ 30d</th>
        <th class="td-center">Δ 60d</th>
        <th class="td-center">14d Trend</th>
        {comp_ths}
      </tr></thead>
      <tbody>{kw_rows}</tbody>
    </table>
  </div>
</div>

<!-- Cost chart + Next posts -->
<div class="two-col">
  <div class="chart-card" style="margin-bottom:0">
    <h3>Daily API Cost — Last 30 Days</h3>
    <canvas id="costChart" height="110"></canvas>
    <p style="font-size:10px;color:#94a3b8;margin-top:8px">claude-sonnet-4-6 · 3 posts/day · ~$0.15/day</p>
  </div>
  <div class="table-card" style="margin-bottom:0">
    <div class="table-header"><h3>Next 10 Scheduled Posts</h3></div>
    <table>
      <thead><tr><th style="width:28px">#</th><th>Topic</th><th class="td-center">Est.</th></tr></thead>
      <tbody>{next_rows}</tbody>
    </table>
  </div>
</div>

<!-- GEO + Recent posts -->
<div class="two-col" style="margin-top:16px">
  <div class="table-card" style="margin-bottom:0">
    <div class="table-header"><h3>GEO Visibility — AI &amp; Search Mentions</h3></div>
    <table>
      <thead><tr><th>Query</th><th class="td-center">Found</th></tr></thead>
      <tbody>{geo_rows}</tbody>
    </table>
  </div>
  <div class="table-card" style="margin-bottom:0">
    <div class="table-header"><h3>Recent Blog Posts</h3></div>
    <table>
      <thead><tr><th>Title</th><th class="td-center">Date</th><th class="td-center">Age</th><th>Keyword</th></tr></thead>
      <tbody>{post_rows}</tbody>
    </table>
  </div>
</div>

</div><!-- /wrap -->

<footer>Velluto SEO Intelligence · <a href="https://github.com/leopold-cell/velluto-seo-bot" style="color:#94a3b8">leopold-cell/velluto-seo-bot</a> · auto-updated daily</footer>

<script>
const BLUE = '#1d4ed8';

// Competitor visibility chart
new Chart(document.getElementById('compChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(comp_labels)},
    datasets: {json.dumps(comp_datasets)}
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ boxWidth: 10, font: {{ size: 10 }} }} }},
      tooltip: {{ callbacks: {{ label: c => c.dataset.label + ': ' + (c.parsed.y ?? '—') + '%' }} }}
    }},
    scales: {{
      y: {{ min: 0, max: 100, ticks: {{ callback: v => v + '%', font: {{ size: 10 }} }}, grid: {{ color: '#f1f5f9' }} }},
      x: {{ ticks: {{ maxTicksLimit: 10, font: {{ size: 10 }} }}, grid: {{ display: false }} }}
    }}
  }}
}});

// Velluto 60-day visibility trend
new Chart(document.getElementById('visChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(vis_labels)},
    datasets: [{{
      label: 'Visibility %',
      data: {json.dumps(vis_scores)},
      borderColor: BLUE,
      backgroundColor: 'rgba(29,78,216,0.08)',
      fill: true,
      tension: 0.4, borderWidth: 2, pointRadius: 0
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: c => c.parsed.y + '%' }} }} }},
    scales: {{
      y: {{ min: 0, max: 100, ticks: {{ callback: v => v + '%', font: {{ size: 10 }} }}, grid: {{ color: '#f1f5f9' }} }},
      x: {{ ticks: {{ maxTicksLimit: 10, font: {{ size: 10 }} }}, grid: {{ display: false }} }}
    }}
  }}
}});

// Cost bar chart
new Chart(document.getElementById('costChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(cost_labels)},
    datasets: [{{ label: 'USD', data: {json.dumps(cost_values)}, backgroundColor: '#1d4ed8', borderRadius: 3 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: c => '$' + c.parsed.y.toFixed(4) }} }} }},
    scales: {{
      y: {{ ticks: {{ callback: v => '$' + v.toFixed(2), font: {{ size: 10 }} }}, beginAtZero: true, grid: {{ color: '#f1f5f9' }} }},
      x: {{ ticks: {{ maxTicksLimit: 12, font: {{ size: 10 }} }}, grid: {{ display: false }} }}
    }}
  }}
}});
</script>
</body>
</html>"""


import json as _json_module
json = _json_module  # make sure json is available in f-string scope


def main():
    print("📊 Building Velluto SEO Dashboard...")
    articles = get_articles(100)
    print(f"   {len(articles)} articles fetched")
    usage    = get_usage()

    print("   Checking keyword rankings vs competitors...")
    ranking_history = check_rankings()

    print("   Checking GEO visibility...")
    geo = check_geo()

    html = build_html(articles, usage, geo, ranking_history)

    out_dir = os.path.join(BASE, "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w") as f:
        f.write(html)

    vis = visibility_score(ranking_history, str(datetime.date.today()))
    geo_found = sum(1 for g in geo if g["found"])
    print(f"   ✓ Dashboard written — Visibility: {vis}% | GEO: {geo_found}/{len(geo)} | Posts: {len(articles)}")


if __name__ == "__main__":
    main()
