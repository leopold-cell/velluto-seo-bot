"""
Surgical legal self-heal for article copy (EU/German advertising law).

ONE canonical implementation of "take an article body and make it legally clean
without regenerating it", shared by:
  • seo_bot.publish_de_primary — the final legal check before a NEW article goes
    live: instead of discarding a whole generated article over a risky phrase, it
    surgically fixes just that phrase and publishes the clean version.
  • scripts/legal_retrofit.py --rewrite — the same fix applied to EXISTING live
    articles in place.

Strategy (cheap → precise, never a full-body regeneration):
  1. Mechanical pass: exact, LLM-free fixes that can't break a sentence
     (strip "(stated)", "Tested & Ranked", em-dashes; correct a false Dutch origin).
  2. Targeted LLM find/replace: hand the model the EXACT flagged phrases and ask
     for minimal compliant replacements (small output, preserves length/links/SEO).
  3. Re-check with quality_gate.check_compliance; loop up to 3 passes.

Returns a clean (title, meta, body) or None if it could not be made clean — the
caller decides what to do with an un-healable article (draft it / skip publish).
NOT legal advice.
"""
from __future__ import annotations

import json
import re as _re

from briefs.quality_gate import (check_compliance, strip_em_dashes,
                                  _FAKE_TEST_RE, _ASYMMETRY_RE, _DISPARAGE_WORD_RE,
                                  _ORIGIN_RE, _near_competitor,
                                  _COMPARATIVE_SUPERLATIVE_RE, _PRICE_DISPARAGE_RE)

HEAL_MODEL = "claude-haiku-4-5-20251001"


def _wc_html(html: str) -> int:
    return len(_re.sub(r"<[^>]+>", " ", html or "").split())


# ── Mechanical fixes (no LLM): safe, exact, can't break sentences ────────────
_STATED_RE = _re.compile(
    r"\s*\(\s*(stated|claimed|self-?reported|allegedly|supposedly|unverified)\s*\)", _re.I)
_TITLE_TEST_RE = _re.compile(
    r"[\s:,\|\-–—]*\b(tested|ranked|compared|comparison|hands[\s-]?on|reviewed?)\b", _re.I)
# Fabricated-test compound ("Tested & Ranked" etc.) — safe to strip from title AND
# body (it echoes into the JSON-LD schema headline); leaves other prose untouched.
_TEST_CLAIM_RE = _re.compile(
    r"\s*[:\|\-–—&,]*\s*\btested\s*(?:,|&|and)\s*(?:and\s+)?(?:ranked|compared)\b"
    r"|\s*[:\|\-–—&,]*\s*\branked\s*(?:,|&|and)\s*(?:and\s+)?tested\b", _re.I)


def _clean_title(title: str) -> str:
    t = _TITLE_TEST_RE.sub("", title or "")
    t = _re.sub(r"\s{2,}", " ", t).strip(" :,|&-–—")
    return t or title


def _fix_origin(text: str) -> str:
    """Mechanically correct a false 'Dutch' origin to German — only inside the
    Velluto-proximity matches the origin check flags (won't touch 'Dutch cyclists')."""
    def _repl(m):
        return _re.sub(r"\b(dutch|nederland\w*|netherland\w*|niederl\w+|hollan\w+)\b",
                       "German", m.group(0), flags=_re.I)
    return _ORIGIN_RE.sub(_repl, text or "")


def _mechanical(title: str, meta: str, body: str):
    title = _clean_title(_TEST_CLAIM_RE.sub("", _fix_origin(_STATED_RE.sub("", title or ""))))
    meta  = _TEST_CLAIM_RE.sub("", _fix_origin(_STATED_RE.sub("", meta or "")))
    body  = _TEST_CLAIM_RE.sub("", _fix_origin(_STATED_RE.sub("", body or "")))
    return strip_em_dashes(title)[0], strip_em_dashes(meta)[0], strip_em_dashes(body)[0]


# ── Targeted LLM find/replace editor ─────────────────────────────────────────
_EDIT_SYSTEM = (
    "You are a legal-compliance editor for a cycling-eyewear brand's OWN blog (Velluto). "
    "Keep the copy punchy and persuasive, but make every competitor mention OBJECTIVE or "
    "POSITIVE — never bashing, never a claim you cannot verify. Find the text that violates "
    "EU/German advertising law and return the minimal replacements to fix it. Violations:\n"
    "1. First-hand TEST/REVIEW claims — 'we tested', 'in our tests', 'hands-on', "
    "'road test', 'after N km/hours', star ratings, 'Testsieger', editorial-test framing. "
    "Reframe as an honest, spec-based buyer's guide.\n"
    "2. Disparaging/doubt-casting statements about named competitors — 'only claims', "
    "'merely', 'degrades', 'inferior', 'cheap', one-sided negatives, absolute 'does not "
    "offer X / doesn't publish its weights'. Use neutral, verifiable facts; describe "
    "Velluto's OWN strengths instead of a rival's weakness.\n"
    "2b. Any fact about a NAMED competitor that isn't 100% verifiable from that "
    "competitor's own public info: rewrite to remove it (general category or Velluto's "
    "own attributes).\n"
    "2c. Unverifiable SUPERLATIVE/comparative claims against a named rival — 'lighter than "
    "anything Oakley makes', 'better than any X', 'the frames are lighter, the fit cleaner'. "
    "Replace with Velluto's OWN measured, verifiable spec (e.g. 'the StradaPro weighs 25 g') "
    "and drop the open-ended comparison.\n"
    "2d. PRICE / VALUE disparagement of a rival — 'subsidise a marketing department', 'what "
    "Oakley charges', 'paying for the logo/name', 'brand tax', 'overpriced', 'rip-off', "
    "'a single Oakley lens replacement'. Never insinuate a competitor overcharges. State "
    "Velluto's own price positioning positively ('premium build from 69 EUR') instead.\n"
    "3. Never attribute photochromic/polarized/mirrored/prescription/over-glasses lenses "
    "to Velluto. Velluto offers only clear VellutoPuro and high-contrast VellutoVisione.\n"
    "4. Velluto is a GERMAN brand (Italian design) — never Dutch/Nederlands.\n"
    "5. The only Velluto price is 'from 69 EUR'; '89 EUR' is the free-shipping threshold, "
    "not the product price.\n"
    "Rules for replacements: same language as the article; similar length (do not shorten "
    "the article); keep any HTML tags/links inside the snippet; never introduce an "
    "em-dash '—'.\n"
    "Return ONLY a JSON array of edits: "
    '[{"find":"<text copied VERBATIM from the article, character-for-character>",'
    '"replace":"<compliant replacement>"}]. Include ONLY real violations. If nothing '
    "needs changing, return []."
)


def _llm_pairs(client, title: str, meta: str, body: str, lang_name: str, feedback: str):
    """Ask for targeted find/replace pairs (small output — no full-body regeneration)."""
    user = (f"LANGUAGE: {lang_name}\n\nAutomated checks flagged this article for:\n{feedback}\n\n"
            f"TITLE:\n{title}\n\nMETA:\n{meta}\n\nBODY_HTML:\n{body}")
    try:
        r = client.messages.create(model=HEAL_MODEL, max_tokens=3000, system=_EDIT_SYSTEM,
                                   messages=[{"role": "user", "content": user}])
        txt = r.content[0].text
    except Exception as e:
        print(f"      edit call failed: {e}")
        return []
    m = _re.search(r"\[.*\]", txt, _re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return [p for p in data if isinstance(p, dict) and p.get("find")]
    except Exception:
        return []


def _apply_pairs(text: str, pairs: list) -> str:
    for p in pairs:
        f = (p.get("find") or "").strip()
        rep = p.get("replace") or ""
        if not f:
            continue
        if f in text:
            text = text.replace(f, rep)
        else:   # whitespace-tolerant fallback (model re-spaced the quote)
            toks = f.split()
            if toks:
                pat = r"\s+".join(_re.escape(t) for t in toks)
                text = _re.sub(pat, lambda _m: rep, text, count=1)
    return text


def _exact_flags(text: str) -> list:
    """The EXACT substrings the compliance regexes flag — handed to the LLM so it can
    target each one precisely (much more reliable than a generic 'fix disparagement')."""
    low = text.lower()
    out = []
    for m in _FAKE_TEST_RE.finditer(text):
        out.append(m.group(0))
    for m in _ASYMMETRY_RE.finditer(text):
        out.append(m.group(0))
    for m in _DISPARAGE_WORD_RE.finditer(text):
        if _near_competitor(low, m.start(), m.end()):
            out.append(text[max(0, m.start() - 60): m.end() + 60])
    for m in _COMPARATIVE_SUPERLATIVE_RE.finditer(text):
        if _near_competitor(low, m.start(), m.end(), window=160):
            out.append(text[max(0, m.start() - 40): m.end() + 80])
    for m in _PRICE_DISPARAGE_RE.finditer(text):
        if _near_competitor(low, m.start(), m.end(), window=200):
            out.append(text[max(0, m.start() - 60): m.end() + 60])
    for m in _ORIGIN_RE.finditer(text):
        out.append(m.group(0))
    seen, res = set(), []
    for s in out:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            res.append(s)
    return res[:15]


def compliance_edit(client, title: str, body: str, meta: str, lang_name: str):
    """Fix ONLY the legal issues: mechanical first (cheap/exact), then targeted LLM
    find/replace pairs for the semantic ones. Returns (title, meta, body) or None if it
    couldn't produce a clean result. Targeted edits preserve content/links/length."""
    title, meta, body = _mechanical(title, meta, body)
    base_wc = max(1, _wc_html(body))
    for _ in range(3):
        issues = check_compliance({"title": title, "meta_description": meta, "body_html": body})
        if not issues:
            break
        flags = _exact_flags(f"{title}\n{meta}\n{body}")
        fb = ("Rewrite/remove EACH of these exact phrases so it no longer implies a "
              "first-hand test, disparages a named competitor, makes an unverifiable "
              "superlative/price claim, or misstates origin:\n"
              + "\n".join(f"- {s!r}" for s in flags)) if flags else "\n".join(issues)
        pairs = _llm_pairs(client, title, meta, body, lang_name, fb)
        if not pairs:
            break
        title = strip_em_dashes(_apply_pairs(title, pairs))[0]
        meta  = strip_em_dashes(_apply_pairs(meta, pairs))[0]
        body  = strip_em_dashes(_apply_pairs(body, pairs))[0]
    if _wc_html(body) < 0.7 * base_wc:                    # sanity: not gutted
        return None
    if check_compliance({"title": title, "meta_description": meta, "body_html": body}):
        return None                                       # still flagged — leave to caller
    return title, (meta or title)[:155], body


def heal_post(post: dict, client, lang_name: str = "English") -> bool:
    """In-place legal self-heal of a generated post dict (title / meta_description /
    body_html). Runs the mechanical + targeted-LLM fix and, if it produces a clean
    version, writes it back into `post`. Returns True if the post is legally clean
    afterwards (either it already was, or it was healed), False if it could not be
    made clean (caller should NOT publish it as-is)."""
    if not check_compliance(post):
        return True
    fixed = compliance_edit(client, post.get("title", ""), post.get("body_html", ""),
                            post.get("meta_description", ""), lang_name)
    if not fixed:
        return False
    post["title"], post["meta_description"], post["body_html"] = fixed
    return True
