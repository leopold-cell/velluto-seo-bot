#!/usr/bin/env python3
"""
Velluto SEO & GEO Dashboard generator.
Fetches live data from Shopify + local logs, outputs docs/index.html for GitHub Pages.
"""

import os, json, datetime, requests, re
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
BLOG_ID       = os.getenv("BLOG_ID", "127785959765")
HEADERS       = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
USAGE_LOG     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token_usage.json")
TOPIC_LOG     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topics_used.json")

TOPIC_POOL = [
    "why UV400 protection matters for road cyclists",
    "how anti-fog cycling glasses work — what to look for",
    "interchangeable lens cycling glasses — are they worth it",
    "how to choose cycling glasses for your face shape",
    "cycling glasses for wind and rain — what to look for",
    "lens categories 0-3 explained for road cyclists",
    "gravel cycling glasses vs road cycling glasses — key differences",
    "how cycling glasses protect against insects, debris and UV",
    "best cycling glasses for long climbs with changing light",
    "why lightweight cycling glasses matter on long rides",
    "how to clean cycling glasses properly without scratching lenses",
    "high contrast lenses for cycling — when you need them",
    "cycling glasses fit guide — adjustable nose pads and frame sizing",
    "best cycling glasses for the Giro and Tour stage conditions",
    "cycling glasses for low light and overcast Dutch weather",
    "what makes road cycling glasses different from regular sunglasses",
    "how to prevent cycling glasses from fogging on cold climbs",
    "clear lens cycling glasses — when and why to use them",
    "the best cycling glasses under €150 in 2026",
    "cycling eye protection — why glasses are non-negotiable equipment",
]


# ── Data fetchers ────────────────────────────────────────────────────────────

def get_articles(limit=50):
    r = requests.get(
        f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
        f"?limit={limit}&fields=id,title,created_at,tags,handle",
        headers=HEADERS, timeout=15
    )
    return r.json().get("articles", [])


def get_usage():
    if not os.path.exists(USAGE_LOG):
        return {}
    return json.load(open(USAGE_LOG))


def get_used_topics():
    if not os.path.exists(TOPIC_LOG):
        return []
    return json.load(open(TOPIC_LOG))


def check_geo_visibility():
    """Search DuckDuckGo for Velluto brand mentions across cycling queries."""
    queries = [
        "best cycling glasses 2026",
        "wielrenbril kopen",
        "Velluto cycling glasses review",
        "StradaPro cycling glasses",
    ]
    results = []
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            for q in queries:
                hits = list(ddgs.text(q, max_results=5))
                found = any("velluto" in (h.get("href","") + h.get("body","")).lower() for h in hits)
                results.append({"query": q, "found": found, "hits": len(hits)})
    except Exception as e:
        results = [{"query": q, "found": False, "hits": 0} for q in queries]
    return results


# ── HTML builder ─────────────────────────────────────────────────────────────

def badge(text, color):
    colors = {
        "green":  ("#d1fae5", "#065f46"),
        "red":    ("#fee2e2", "#991b1b"),
        "yellow": ("#fef3c7", "#92400e"),
        "gray":   ("#f3f4f6", "#374151"),
        "blue":   ("#dbeafe", "#1e40af"),
    }
    bg, fg = colors.get(color, colors["gray"])
    return f'<span style="background:{bg};color:{fg};padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600;">{text}</span>'


def sparkline(values, width=120, height=32):
    if not values or max(values) == 0:
        return ""
    mx = max(values)
    pts = []
    for i, v in enumerate(values):
        x = i * width / max(len(values) - 1, 1)
        y = height - (v / mx * height * 0.9) - 2
        pts.append(f"{x:.1f},{y:.1f}")
    path = " ".join(pts)
    return (f'<svg width="{width}" height="{height}" style="vertical-align:middle">'
            f'<polyline points="{path}" fill="none" stroke="#111" stroke-width="2" stroke-linejoin="round"/>'
            f'</svg>')


def build_html(articles, usage, used_topics, geo):
    today = datetime.date.today()
    now   = datetime.datetime.now().strftime("%d %b %Y, %H:%M")

    # ── Stats ──
    total_posts  = len(articles)
    posts_30d    = sum(1 for a in articles if a["created_at"][:10] >= str(today - datetime.timedelta(days=30)))
    total_cost   = sum(v["cost_usd"] for v in usage.values())
    cost_30d     = sum(v["cost_usd"] for k, v in usage.items()
                       if datetime.date.fromisoformat(k) >= today - datetime.timedelta(days=30))
    days_active  = len(usage)
    topics_done  = len(used_topics)
    topics_left  = len([t for t in TOPIC_POOL if t not in used_topics])
    geo_score    = sum(1 for g in geo if g["found"])

    # ── Daily cost sparkline (last 14 days) ──
    spark_days   = [(today - datetime.timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    spark_values = [usage.get(d, {}).get("cost_usd", 0) for d in spark_days]

    # ── Article rows ──
    article_rows = ""
    for a in articles[:30]:
        date  = a["created_at"][:10]
        tags  = a.get("tags", "")
        kw    = tags.split(",")[0].strip() if tags else "—"
        age   = (today - datetime.date.fromisoformat(date)).days
        age_b = badge(f"{age}d ago", "green" if age <= 3 else "gray")
        article_rows += f"""
        <tr>
          <td style="padding:10px 12px;color:#111;font-weight:500">{a['title']}</td>
          <td style="padding:10px 12px;color:#6b7280;font-size:13px">{date}</td>
          <td style="padding:10px 12px">{age_b}</td>
          <td style="padding:10px 12px;color:#6b7280;font-size:12px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{kw}</td>
        </tr>"""

    # ── Topic rows ──
    topic_rows = ""
    for t in TOPIC_POOL:
        done = t in used_topics
        icon = "✓" if done else "○"
        color = "#065f46" if done else "#9ca3af"
        bg   = "#f0fdf4" if done else "#fff"
        topic_rows += f"""
        <tr style="background:{bg}">
          <td style="padding:8px 12px;color:{color};font-weight:700;font-size:14px">{icon}</td>
          <td style="padding:8px 12px;color:#374151;font-size:13px">{t}</td>
        </tr>"""

    # ── GEO rows ──
    geo_rows = ""
    for g in geo:
        found_b = badge("Found ✓", "green") if g["found"] else badge("Not found", "red")
        geo_rows += f"""
        <tr>
          <td style="padding:10px 12px;font-size:13px;color:#374151">{g['query']}</td>
          <td style="padding:10px 12px">{found_b}</td>
        </tr>"""

    geo_pct = int(geo_score / max(len(geo), 1) * 100)
    geo_color = "green" if geo_pct >= 75 else "yellow" if geo_pct >= 40 else "red"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Velluto SEO Dashboard</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9fafb;color:#111;min-height:100vh}}
    .top{{background:#111;color:#fff;padding:20px 32px;display:flex;justify-content:space-between;align-items:center}}
    .top h1{{font-size:18px;font-weight:700;letter-spacing:.5px}}
    .top span{{font-size:12px;opacity:.6}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;padding:24px 32px 0}}
    .card{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px}}
    .card .label{{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:#9ca3af;margin-bottom:6px}}
    .card .value{{font-size:32px;font-weight:800;color:#111}}
    .card .sub{{font-size:12px;color:#6b7280;margin-top:4px}}
    .section{{margin:24px 32px 0}}
    .section h2{{font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#6b7280;margin-bottom:12px}}
    table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}}
    th{{background:#f9fafb;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#9ca3af;padding:10px 12px;text-align:left;font-weight:600}}
    tr:not(:last-child){{border-bottom:1px solid #f3f4f6}}
    tr:hover{{background:#fafafa}}
    .geo-bar{{height:8px;border-radius:4px;background:#e5e7eb;margin-top:8px}}
    .geo-fill{{height:8px;border-radius:4px;background:#111;transition:width .5s}}
    footer{{text-align:center;padding:32px;font-size:12px;color:#9ca3af}}
  </style>
</head>
<body>

<div class="top">
  <h1>🚴 Velluto SEO &amp; GEO Dashboard</h1>
  <span>Updated {now} · velluto-shop.com</span>
</div>

<div class="grid">
  <div class="card">
    <div class="label">Total posts</div>
    <div class="value">{total_posts}</div>
    <div class="sub">{posts_30d} in last 30 days</div>
  </div>
  <div class="card">
    <div class="label">Topics covered</div>
    <div class="value">{topics_done}</div>
    <div class="sub">{topics_left} remaining in pool</div>
  </div>
  <div class="card">
    <div class="label">Total API cost</div>
    <div class="value">${total_cost:.2f}</div>
    <div class="sub">${cost_30d:.2f} last 30 days</div>
  </div>
  <div class="card">
    <div class="label">Days active</div>
    <div class="value">{days_active}</div>
    <div class="sub">since launch</div>
  </div>
  <div class="card">
    <div class="label">GEO visibility</div>
    <div class="value">{geo_score}/{len(geo)}</div>
    <div class="sub">{badge(f'{geo_pct}% found', geo_color)}</div>
    <div class="geo-bar"><div class="geo-fill" style="width:{geo_pct}%"></div></div>
  </div>
  <div class="card">
    <div class="label">Daily cost (14d)</div>
    <div class="value" style="font-size:18px;padding-top:4px">{sparkline(spark_values)}</div>
    <div class="sub">avg ${(sum(spark_values)/max(len([v for v in spark_values if v>0]),1)):.2f}/day</div>
  </div>
</div>

<div class="section">
  <h2>GEO Visibility — Brand in Search</h2>
  <table>
    <thead><tr><th>Search Query</th><th>Velluto Found</th></tr></thead>
    <tbody>{geo_rows}</tbody>
  </table>
</div>

<div class="section">
  <h2>Published Blog Posts</h2>
  <table>
    <thead><tr><th>Title</th><th>Date</th><th>Age</th><th>Keyword</th></tr></thead>
    <tbody>{article_rows}</tbody>
  </table>
</div>

<div class="section">
  <h2>Topic Coverage</h2>
  <table>
    <thead><tr><th style="width:40px"></th><th>Topic</th></tr></thead>
    <tbody>{topic_rows}</tbody>
  </table>
</div>

<footer>Velluto SEO Bot · Auto-updated daily via GitHub Actions · <a href="https://github.com/leopold-cell/velluto-seo-bot" style="color:#111">leopold-cell/velluto-seo-bot</a></footer>

</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("📊 Building Velluto SEO Dashboard...")
    print("   Fetching articles...")
    articles    = get_articles(50)
    usage       = get_usage()
    used_topics = get_used_topics()
    print("   Checking GEO visibility...")
    geo         = check_geo_visibility()

    html = build_html(articles, usage, used_topics, geo)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w") as f:
        f.write(html)

    print(f"   ✓ Dashboard written to {out_path}")
    geo_found = sum(1 for g in geo if g["found"])
    print(f"   GEO: {geo_found}/{len(geo)} queries find Velluto")
    print(f"   Posts: {len(articles)} total")


if __name__ == "__main__":
    main()
