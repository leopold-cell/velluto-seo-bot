"""
Split article HTML into an exact structure skeleton + the translatable text segments,
and put adapted segments back into the identical skeleton.

Why: market adaptation used to hand the whole HTML body to the LLM and have it rewrite
everything IN the target language — re-emitting every <div>, class, id and URL as output
tokens (zero SEO value) and risking truncation / mangled tags. Instead we let the model
ADAPT only the text (keyword, local context, native phrasing) and reinsert it into the
byte-identical skeleton. Structure integrity is guaranteed, tokens drop sharply, and
truncation is impossible.

Dependency-free (stdlib regex). The split is exact by construction:
    detokenize(*tokenize(h)) == h   for any h
so a mismatch is always detectable and the caller can fall back to full-body adaptation.

This is NOT a plain translation: the caller still passes the market keyword + local
context to the adaptation model, and heading/opening segments are flagged so the keyword
is woven in exactly where on-page SEO needs it. Native PAA (new content) is generated
separately and appended by the caller.
"""
from __future__ import annotations

import re

# Tags (with their attributes / URLs / class names) are delimiters; text lives between
# them. Article bodies contain no <style>/<script> (CSS is wrapped in post-hoc), so a
# plain tag split is safe and exact.
_TAG_SPLIT = re.compile(r"(<[^>]+>)")
# Translatable attribute values inside a tag (image alt text, title tooltips).
_ATTR_RE = re.compile(r'(\b(?:alt|title)\s*=\s*")([^"]*)(")', re.I)
# Opening tag name (to flag headings / first paragraph for keyword placement).
_OPEN_TAG_RE = re.compile(r"^<\s*([a-zA-Z0-9]+)")
_HEADING_TAGS = {"h1", "h2", "h3"}


def tokenize(html: str):
    """Return (parts, segments, roles).

    parts    : list mixing literal markup strings and int placeholders (index into
               segments) where translatable text was.
    segments : the translatable strings, in document order (text nodes + alt/title).
    roles    : list parallel to segments — 'h1'/'h2'/'h3' for heading text, 'attr' for
               alt/title values, 'body' otherwise. Lets the caller tell the model which
               segments are SEO-critical (weave the keyword there).
    """
    parts: list = []
    segments: list[str] = []
    roles: list[str] = []
    cur_tag = ""          # most recent opening tag name (for heading detection)

    def add_seg(s: str, role: str):
        segments.append(s)
        roles.append(role)
        parts.append(len(segments) - 1)

    for chunk in _TAG_SPLIT.split(html or ""):
        if not chunk:
            continue
        if chunk.startswith("<") and chunk.endswith(">"):
            m_open = _OPEN_TAG_RE.match(chunk)
            if m_open:
                cur_tag = m_open.group(1).lower()
            # keep the tag literal, but lift out any alt/title value as a segment
            last = 0
            for m in _ATTR_RE.finditer(chunk):
                parts.append(chunk[last:m.start()])
                parts.append(m.group(1))            # ` alt="`
                if m.group(2).strip():
                    add_seg(m.group(2), "attr")
                else:
                    parts.append(m.group(2))
                parts.append(m.group(3))            # closing quote
                last = m.end()
            parts.append(chunk[last:])
        else:
            if chunk.strip():
                add_seg(chunk, cur_tag if cur_tag in _HEADING_TAGS else "body")
            else:
                parts.append(chunk)                 # whitespace between tags — keep as-is
    return parts, segments, roles


def detokenize(parts: list, segments: list) -> str:
    """Rebuild HTML from parts, substituting each int placeholder with segments[i].
    With the ORIGINAL segments this reproduces the input exactly; with adapted segments
    it yields the adapted article in the identical skeleton."""
    out: list[str] = []
    for p in parts:
        if isinstance(p, int):
            out.append(segments[p] if 0 <= p < len(segments) else "")
        else:
            out.append(p)
    return "".join(out)


def first_body_index(roles: list) -> int:
    """Index of the first real body/heading segment (the opening line) or -1."""
    for i, r in enumerate(roles):
        if r != "attr":
            return i
    return -1
