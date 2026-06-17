"""
Per-article quality audit.

Reuses the deterministic checks from briefs/quality_gate.py (read-only — we do
NOT mutate/auto-fix live content here) and adds an optional LLM quality score
(depth, readability, helpfulness, E-E-A-T, AI-writing tells) via Haiku.
"""
from __future__ import annotations

from review import inventory
from review._common import HAIKU, complete, parse_json_block, have_anthropic

# Reuse the existing gate checks without triggering its auto-fix mutations.
from briefs import quality_gate as qg


def _deterministic_issues(article: dict) -> list[str]:
    primary = inventory.primary_keyword(article)
    post = {
        "title": article.get("title", ""),
        "body_html": article.get("body_html", ""),
        "meta_description": article.get("summary_html", ""),
        "keyword": primary,
    }
    issues: list[str] = []
    if primary:
        issues += qg.check_keyword_in_title_h1(post, primary)
    issues += qg.check_word_count(post)
    issues += qg.check_internal_links(post)
    issues += qg.check_brand_facts(post)
    issues += qg.check_no_markdown_fence(post)
    issues += qg.check_image_alt_text(post)
    return issues


_SCORE_SYSTEM = (
    "You are a senior SEO content editor for Velluto, a premium cycling-eyewear brand. "
    "Rate ONE article's body HTML. Be strict and concise. Return ONLY JSON: "
    '{"score": 0-100, "verdict": "strong|ok|weak", '
    '"strengths": ["..."], "issues": ["..."], "ai_tells": ["..."]}. '
    "Judge depth, helpfulness, originality, E-E-A-T signals, scannability, and "
    "whether it reads like generic AI filler."
)


def _llm_score(article: dict) -> dict | None:
    if not have_anthropic():
        return None
    body = (article.get("body_html") or "")[:14000]
    user = f"TITLE: {article.get('title','')}\n\nBODY_HTML:\n{body}"
    out = complete(_SCORE_SYSTEM, user, model=HAIKU, max_tokens=500)
    parsed = parse_json_block(out)
    return parsed if isinstance(parsed, dict) else None


def audit_article(article: dict, deep: bool = True) -> dict:
    det = _deterministic_issues(article)
    score = _llm_score(article) if deep else None
    sev = "ok"
    if det:
        sev = "warning"
    if score and score.get("verdict") == "weak":
        sev = "critical"
    return {
        "id": article.get("id"),
        "handle": article.get("handle"),
        "title": article.get("title"),
        "word_count": article.get("word_count"),
        "deterministic_issues": det,
        "llm_score": score,
        "severity": sev,
    }


def audit(articles: list[dict], deep: bool = True) -> dict:
    results = [audit_article(a, deep=deep) for a in articles]
    scored = [r["llm_score"]["score"] for r in results
              if r.get("llm_score") and isinstance(r["llm_score"].get("score"), (int, float))]
    return {
        "articles_checked": len(results),
        "avg_llm_score": round(sum(scored) / len(scored), 1) if scored else None,
        "with_issues": sum(1 for r in results if r["deterministic_issues"]),
        "weak": sum(1 for r in results if r["severity"] == "critical"),
        "results": results,
    }
