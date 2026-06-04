"""
Pre-publish quality gate (spec line 1610-1643).

Two-tier model:
  AUTO-FIX (silent):
    - Strip <a> tags pointing at competitor domains (text kept)
    - Inject mandatory homepage link in CTA if missing
    - Trim oversized meta_title / meta_description

  HARD-FAIL (blocks publish, logs to output/quality_gate_failures.json):
    - Primary keyword missing from title OR H1
    - Article body shorter than 600 words
    - Hard-coded price strings that disagree with current commercial config
    - Mandatory PAA questions (from brief) have no corresponding H2 in the body
    - No internal links at all

When HARD-FAIL occurs, the bot logs the issue and exits cleanly without
publishing (per Phase 4 decision: "Block publish, log, exit").
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any

import config_loader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILURES_LOG = os.path.join(ROOT, "output", "quality_gate_failures.json")

HOMEPAGE_URL = "https://velluto-shop.com"
HOMEPAGE_HREF = "/"  # root-relative homepage used for in-body links
INTERNAL_REL_PREFIXES = ("/products/", "/collections/", "/blogs/", "/pages/")
MIN_WORD_COUNT = 600


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def _word_count(html: str) -> int:
    return len(_strip_html(html).split())


# ── Auto-fix step 1: strip competitor outbound links ──────────────────────

def strip_competitor_links(html: str) -> tuple[str, list[str]]:
    """
    Find any <a href="..."> pointing at a forbidden competitor domain.
    Strip the <a> wrapper but keep the inner text.
    Returns (fixed_html, list_of_stripped_domains).
    """
    forbidden = config_loader.forbidden_outbound_domains()
    if not forbidden:
        return html, []
    stripped: list[str] = []

    def _repl(m: re.Match) -> str:
        href = m.group(1).lower()
        for dom in forbidden:
            if dom in href:
                stripped.append(dom)
                # Drop the <a ...> opener AND the matching </a>
                inner = m.group(2)
                return inner
        return m.group(0)

    pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         re.IGNORECASE | re.DOTALL)
    fixed = pattern.sub(_repl, html)
    return fixed, stripped


# ── Auto-fix step 2: inject mandatory homepage link ───────────────────────

def ensure_homepage_link(html: str) -> tuple[str, bool]:
    """
    If the homepage is not linked anywhere in the body (either as the absolute
    URL or as a root-relative href="/"), inject a natural link near the end
    (before any FAQ section, falling back to body end).
    Returns (fixed_html, injected_bool).
    """
    if HOMEPAGE_URL in html or re.search(r'href=["\']/["\']', html):
        return html, False

    anchor_options = [
        "Velluto cycling eyewear", "Velluto", "premium cycling glasses by Velluto",
        "Velluto Strada Pro", "Velluto's cycling glasses collection",
    ]
    # Deterministic pick — use first option that's not already an anchor elsewhere
    anchor_text = anchor_options[0]
    injection = f'<p>Discover more about <a href="{HOMEPAGE_HREF}">{anchor_text}</a>.</p>'

    # Prefer injection right before FAQ block; else right before </body> equivalent (end of html)
    if re.search(r'<h2[^>]*id=["\']sfaq', html, re.I):
        fixed = re.sub(r'(<h2[^>]*id=["\']sfaq)', injection + r"\1", html, count=1, flags=re.I)
    elif re.search(r'<details', html, re.I):
        fixed = re.sub(r'(<details)', injection + r"\1", html, count=1, flags=re.I)
    else:
        fixed = html + "\n" + injection

    return fixed, True


def strip_em_dashes(html: str) -> tuple[str, bool]:
    """
    Phase 4.11: remove the em-dash '—' (and spaced en-dash ' – ') used as a
    sentence pause — the classic AI-writing tell. Replaced with a comma.

    Preserves: hyphens in compound words (anti-fog, UV400-certified, 30-day),
    URL slugs, and number ranges like '10–20' (en-dash WITHOUT surrounding spaces).
    """
    orig = html
    html = re.sub(r'\s*—\s*', ', ', html)   # em-dash (with/without spaces) → comma
    html = re.sub(r'\s+–\s+', ', ', html)   # ONLY spaced en-dash (pause) → comma; "10–20" stays
    # tidy up artifacts
    html = re.sub(r',\s*,', ', ', html)     # double comma
    html = re.sub(r'\s+,', ',', html)       # space before comma
    html = re.sub(r',\s*\.', '.', html)     # comma before period
    html = re.sub(r',\s*(</)', r'\1', html) # trailing comma before closing tag
    return html, (html != orig)


# ── HARD checks ────────────────────────────────────────────────────────────

def check_keyword_in_title_h1(post: dict, primary_keyword: str) -> list[str]:
    issues = []
    title = (post.get("title") or "").lower()
    body  = post.get("body_html") or ""
    kw    = primary_keyword.lower()
    kw_tokens = set(re.findall(r"\w+", kw))

    title_tokens = set(re.findall(r"\w+", title))
    if len(kw_tokens & title_tokens) < max(2, len(kw_tokens) - 2):
        issues.append(f"[KEYWORD] primary_keyword '{primary_keyword}' missing from title: '{title[:60]}'")

    h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', body, re.I | re.S)
    if h1_match:
        h1_text = _strip_html(h1_match.group(1)).lower()
        h1_tokens = set(re.findall(r"\w+", h1_text))
        if len(kw_tokens & h1_tokens) < max(2, len(kw_tokens) - 2):
            issues.append(f"[KEYWORD] primary_keyword missing from H1: '{h1_text[:60]}'")
    else:
        # No H1 might be OK if title rendered separately by template; just warn
        pass
    return issues


def check_word_count(post: dict) -> list[str]:
    wc = _word_count(post.get("body_html", ""))
    if wc < MIN_WORD_COUNT:
        return [f"[WORD_COUNT] only {wc} words (min {MIN_WORD_COUNT})"]
    return []


VELLUTO_CONTEXT_TOKENS = (
    "velluto", "strada", "vellutopuro", "vellutovisione",
)
VELLUTO_CSS_TOKENS = ("product-price",)  # CSS class on product-card price div


def _is_velluto_price_context(body: str, match_start: int, match_end: int,
                              window: int = 80) -> bool:
    """
    Determines whether a price token is being attributed to Velluto.

    Logic: "same sentence wins."
      1. If the price is inside a class="product-price" element → Velluto.
      2. Otherwise find the SENTENCE containing the price.
         - If sentence mentions Velluto AND no competitor → Velluto.
         - If sentence mentions a competitor brand → skip (competitor's price).
         - If sentence has neither → check neighbouring sentence (within ±window).
         - If no brand anywhere nearby → market context, skip.
    """
    # 1. Inside a product-price CSS class → clearly Velluto
    snippet_wide = body[max(0, match_start - 60): match_end + 60].lower()
    if any(css in snippet_wide for css in VELLUTO_CSS_TOKENS):
        return True

    # Build competitor brand tokens
    competitors = config_loader.forbidden_outbound_domains()
    competitor_tokens = set()
    for d in competitors:
        brand = d.split(".")[0].lower()
        if len(brand) >= 3:
            competitor_tokens.add(brand)
    competitor_tokens.update({"oakley", "poc", "uvex", "rudy", "tifosi",
                              "scicon", "alba", "rapha", "evil eye", "100%"})

    def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
        """Find the sentence boundaries (period, ?, !, or <p> tag) around pos."""
        # Scan backwards for sentence start
        start = 0
        for end_token in [". ", "? ", "! ", "<p>", "</p>", "<br>", "<h1>", "<h2>"]:
            i = text.rfind(end_token, 0, pos)
            if i > start:
                start = i + len(end_token)
        # Scan forwards for sentence end
        end = len(text)
        for end_token in [". ", "? ", "! ", "</p>", "<br>", "</h1>", "</h2>"]:
            i = text.find(end_token, pos)
            if i != -1 and i < end:
                end = i
        return start, end

    body_lower = body.lower()
    s_start, s_end = _sentence_bounds(body_lower, match_start)
    sentence = body_lower[s_start:s_end]

    has_velluto_in_sentence    = any(t in sentence for t in VELLUTO_CONTEXT_TOKENS)
    has_competitor_in_sentence = any(t in sentence for t in competitor_tokens)

    if has_competitor_in_sentence:
        return False  # the sentence is about a competitor — their price
    if has_velluto_in_sentence:
        return True   # same sentence as Velluto and no competitor — Velluto's price

    # Neither brand in this sentence — fall back to small-window check
    snippet = body_lower[max(0, match_start - 40): match_end + 40]
    if any(t in snippet for t in competitor_tokens):
        return False
    if any(t in snippet for t in VELLUTO_CONTEXT_TOKENS):
        return True
    return False  # market context


def check_commercial_config(post: dict, market_code: str, commercial: dict | None) -> list[str]:
    """
    Flag VELLUTO-CONTEXT prices in the body that don't match the current
    commercial config. Prices presented as competitor/market context are
    intentionally NOT flagged — those are legitimate comparison content.
    """
    if not commercial:
        return []
    cfg = commercial.get(market_code) or {}
    expected = cfg.get("current_price")
    expected_curr = cfg.get("currency")
    if not expected or not expected_curr:
        return []

    body = post.get("body_html", "")
    issues: list[str] = []
    money_patterns = [
        (r"€\s*(\d{2,4})(?:[.,]\d{2})?",         "EUR"),
        (r"\$\s*(\d{2,4})(?:[.,]\d{2})?",         "USD"),
        (r"(\d{2,4})\s*EUR\b",                    "EUR"),
        (r"(\d{2,4})\s*USD\b",                    "USD"),
        (r"(\d{2,4})\s*DKK\b",                    "DKK"),
        (r"(\d{2,4})\s*NOK\b",                    "NOK"),
        (r"(\d{2,4})\s*PLN\b",                    "PLN"),
        (r"(\d{2,4})\s*SEK\b",                    "SEK"),
    ]
    for pat, curr in money_patterns:
        for m in re.finditer(pat, body):
            try:
                amt = int(m.group(1))
            except Exception:
                continue
            if not (30 <= amt <= 5000):
                continue
            # ── Only flag if this price is attributed to Velluto ──
            if not _is_velluto_price_context(body, m.start(), m.end()):
                continue
            # Tolerate exact match + UVP strikethrough
            if curr == expected_curr and amt == expected:
                continue
            if cfg.get("uvp") and curr == expected_curr and amt == cfg["uvp"]:
                continue
            issues.append(
                f"[PRICE] Velluto-context price '{amt} {curr}' but config expects "
                f"'{expected} {expected_curr}' for {market_code}"
            )
    return list(dict.fromkeys(issues))  # dedupe preserving order


# Phase 4.4: Velluto doesn't offer photochromic, polarized, or prescription lenses.
# Articles may discuss these features in competitor or informational context, but
# must NEVER attribute them to Velluto products. Sentence-based attribution
# (reusing _is_velluto_price_context) distinguishes the two cases.
FORBIDDEN_FEATURE_TOKENS = [
    ("photochrom", "claims photochromic lenses — Velluto doesn't offer these"),
    ("polari",     "claims polarized lenses — Velluto doesn't offer these"),
    # 'polari' prefix matches both 'polarized' (US) and 'polarised' (UK)
]


def check_image_alt_text(post: dict) -> list[str]:
    """Phase 4.9b: flag <img> tags with missing, empty, or placeholder alt text."""
    body = post.get("body_html", "")
    issues: list[str] = []
    for m in re.finditer(r'<img\b[^>]*>', body, re.IGNORECASE):
        tag = m.group(0)
        alt = re.search(r'\balt\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
        val = (alt.group(1).strip() if alt else "")
        if not alt or not val or val in ("...", "[Product name]") or val.startswith("["):
            issues.append(f"[ALT] <img> missing/placeholder alt text: {tag[:80]}")
    # one issue line is enough to trigger a regen; cap noise
    return issues[:1]


def check_no_markdown_fence(post: dict) -> list[str]:
    """Phase 4.7: catch a leaked ```html / ``` markdown fence in the body."""
    body = post.get("body_html", "")
    if re.search(r'```', body):
        return ["[FENCE] body contains a markdown code fence (```), strip before publish"]
    return []


def check_brand_facts(post: dict) -> list[str]:
    """
    Flag VELLUTO-attributed claims about features Velluto doesn't offer.
    Competitor-attributed and market-context mentions are NOT flagged.

    Examples:
      "Velluto's polarized lenses..."                          → FLAGGED
      "Oakley uses polarized lenses; Velluto chose UV400"      → NOT flagged
      "Photochromic vs interchangeable: which for cycling?"    → NOT flagged
      "Velluto doesn't offer polarized; Oakley does."          → NOT flagged
         (sentence has both brands → competitor wins per the helper logic)
    """
    body = (post.get("body_html") or "").lower()
    issues: list[str] = []
    for token, msg in FORBIDDEN_FEATURE_TOKENS:
        # one flag per token type is enough — break after first hit
        for m in re.finditer(token, body):
            if _is_velluto_price_context(body, m.start(), m.end()):
                issues.append(f"[FACT] {msg}")
                break
    return issues


def check_paa_coverage(post: dict, brief: dict | None) -> list[str]:
    """If brief has must_answer_questions, ensure at least 50% appear as H2s in the body."""
    if not brief or not brief.get("must_answer_questions"):
        return []
    questions = brief["must_answer_questions"]
    body = post.get("body_html", "")
    h2s = [_strip_html(h).lower() for h in re.findall(r'<h2[^>]*>(.*?)</h2>', body, re.I | re.S)]
    covered = 0
    for q in questions:
        q_tokens = set(re.findall(r"\w+", q.lower())) - {"the", "a", "an", "for", "to", "is", "are"}
        for h in h2s:
            h_tokens = set(re.findall(r"\w+", h))
            if len(q_tokens & h_tokens) >= max(2, len(q_tokens) // 2):
                covered += 1
                break
    if covered < max(1, len(questions) // 2):
        return [f"[PAA] only {covered}/{len(questions)} mandatory PAA questions have an H2 match"]
    return []


def check_internal_links(post: dict) -> list[str]:
    body = post.get("body_html", "")
    links = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\']', body, re.I)
    internal_links = [
        l for l in links
        if "velluto-shop.com" in l.lower()
        or l == "/" or l.startswith(INTERNAL_REL_PREFIXES)
    ]
    if len(internal_links) < 1:
        return ["[INTERNAL_LINKS] no Velluto internal links present"]
    return []


def check_meta_lengths(post: dict) -> list[str]:
    issues = []
    mt_len = len((post.get("title") or ""))
    md_len = len((post.get("meta_description") or ""))
    if mt_len > 65:
        issues.append(f"[META] title length {mt_len} > 65")
    if md_len > 160:
        issues.append(f"[META] meta_description length {md_len} > 160")
    return issues


# ── Top-level gate ────────────────────────────────────────────────────────

def gate(post: dict, brief: dict | None, market_code: str = "US",
         commercial: dict | None = None) -> dict:
    """
    Run all checks. Mutates post.body_html in place for auto-fixes.
    Returns:
      {
        passed: bool,
        auto_fixes: ["stripped 2 competitor links", "injected homepage link"],
        hard_issues: [...],
        soft_issues: [],
      }
    """
    primary_keyword = (brief or {}).get("primary_keyword") or post.get("keyword") or ""

    auto_fixes: list[str] = []
    body = post.get("body_html", "")
    # Auto-fix 1: strip competitor links
    fixed_body, stripped = strip_competitor_links(body)
    if stripped:
        auto_fixes.append(f"stripped {len(stripped)} competitor link(s): {sorted(set(stripped))}")
    # Auto-fix 2: inject homepage link
    fixed_body, injected = ensure_homepage_link(fixed_body)
    if injected:
        auto_fixes.append("injected mandatory homepage link")
    # Auto-fix 3: strip em-dashes (Phase 4.11 — the AI-writing tell)
    fixed_body, dashed = strip_em_dashes(fixed_body)
    if dashed:
        auto_fixes.append("replaced em-dashes with commas")
    post["body_html"] = fixed_body

    # Hard checks
    hard: list[str] = []
    hard += check_keyword_in_title_h1(post, primary_keyword) if primary_keyword else []
    hard += check_word_count(post)
    hard += check_internal_links(post)
    hard += check_meta_lengths(post)
    hard += check_paa_coverage(post, brief)
    hard += check_commercial_config(post, market_code, commercial)
    hard += check_brand_facts(post)        # Phase 4.4 sentence-aware FACT check
    hard += check_no_markdown_fence(post)  # Phase 4.7 leaked ```html fence
    hard += check_image_alt_text(post)     # Phase 4.9b blank/placeholder img alt

    passed = not hard

    result = {
        "passed":      passed,
        "auto_fixes":  auto_fixes,
        "hard_issues": hard,
        "primary_keyword": primary_keyword,
        "market":      market_code,
        "checked_at":  _dt.datetime.utcnow().isoformat() + "Z",
    }
    if not passed:
        _log_failure(post, brief, result)
    return result


def _log_failure(post: dict, brief: dict | None, result: dict) -> None:
    """Append a failure record to output/quality_gate_failures.json."""
    log: list = []
    if os.path.exists(FAILURES_LOG):
        try:
            log = json.load(open(FAILURES_LOG))
            if not isinstance(log, list):
                log = []
        except Exception:
            log = []
    log.append({
        **result,
        "title":          post.get("title"),
        "primary_keyword": result["primary_keyword"],
        "brief_topic":    (brief or {}).get("topic"),
    })
    log = log[-200:]  # keep last 200
    os.makedirs(os.path.dirname(FAILURES_LOG), exist_ok=True)
    with open(FAILURES_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    # Standalone test
    sample = {
        "title": "Best Cycling Sunglasses for Road Cycling 2026",
        "body_html": (
            "<h1>Best Cycling Sunglasses for Road Cycling</h1>"
            "<p>Lorem ipsum about cycling glasses and UV400 protection. "
            "Premium <a href='https://oakley.com/sutro'>Oakley Sutro</a> is great, "
            "but Velluto offers better value. " + ("Lorem ipsum. " * 200) + "</p>"
            "<h2>What are the best cycling sunglasses?</h2>"
            "<p>Look for UV400 and anti-fog. " + ("Filler. " * 50) + "</p>"
        ),
        "meta_description": "Find the best cycling sunglasses with UV400, anti-fog and Italian design.",
        "keyword": "best cycling sunglasses",
    }
    brief = {
        "primary_keyword": "best cycling sunglasses",
        "must_answer_questions": ["What are the best cycling sunglasses?",
                                   "Are expensive cycling sunglasses worth it?"],
        "topic": "best cycling sunglasses",
    }
    r = gate(sample, brief, market_code="US", commercial=None)
    print(json.dumps(r, indent=2))
    print("--- POST-GATE HTML (snippet) ---")
    print(sample["body_html"][:500])
