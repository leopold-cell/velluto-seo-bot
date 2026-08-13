"""
Brand-agnostic AI-answer probe: ask an engine a question, record who got cited.

The Velluto monitors (scripts/perplexity_monitor.py, scripts/chatgpt_monitor.py)
each hardcode ONE domain and answer one question: "were we cited?". The same
mechanism answers a much more useful question when you make the brand list a
parameter: "who was cited, and who wasn't?".

That inversion is the product. For a prospect, "competitors cited, prospect not"
is both the qualifying signal and the pitch.

Engines are optional at runtime — a missing key yields None rather than an
exception, so a pipeline step can no-op like every other guarded call here.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field, asdict

import requests

PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = os.getenv("PERPLEXITY_MODEL", "sonar")
CHATGPT_MODEL = os.getenv("CHATGPT_MONITOR_MODEL", "gpt-5")


@dataclass(frozen=True)
class Brand:
    """A brand to look for in an answer. `key` is the stable identifier."""
    key: str
    domain: str
    aliases: tuple[str, ...] = ()

    def matches_url(self, url: str) -> bool:
        return bool(self.domain) and self.domain in url

    def matches_text(self, text: str) -> bool:
        low = (text or "").lower()
        if self.domain and self.domain in low:
            return True
        return any(a.lower() in low for a in self.aliases if a)


@dataclass
class ProbeResult:
    engine: str
    question: str
    asked_at: str
    cited_domains: list[str] = field(default_factory=list)
    answer_text: str = ""
    # brand key -> {"cited": bool, "mentioned": bool}
    brands: dict[str, dict[str, bool]] = field(default_factory=dict)
    error: str = ""

    def cited_keys(self) -> list[str]:
        return sorted(k for k, v in self.brands.items() if v.get("cited"))

    def to_dict(self) -> dict:
        return asdict(self)


def domain_of(url: str) -> str:
    """Bare host for a URL ('' when unparseable). Mirrors scripts/geo_questions."""
    if not isinstance(url, str):
        return ""
    host = url.split("//")[-1].split("/")[0].strip().lower()
    return host[4:] if host.startswith("www.") else host


def _score_brands(brands: list[Brand], urls: list[str], text: str) -> dict[str, dict[str, bool]]:
    """
    Split "cited" (a real source link) from "mentioned" (named in prose only).
    They are different products: a citation drives referral traffic, a mention
    only shapes perception. Conflating them would overstate visibility.
    """
    out: dict[str, dict[str, bool]] = {}
    for b in brands:
        cited = any(b.matches_url(u) for u in urls) or (bool(b.domain) and b.domain in (text or ""))
        mentioned = (not cited) and b.matches_text(text)
        out[b.key] = {"cited": cited, "mentioned": mentioned}
    return out


def _dedupe_domains(urls: list[str]) -> list[str]:
    seen: list[str] = []
    for u in urls:
        d = domain_of(u)
        if d and d not in seen:
            seen.append(d)
    return seen


def probe_perplexity(question: str, brands: list[Brand],
                     timeout: int = 60, api_key: str | None = None) -> ProbeResult | None:
    """One Perplexity (sonar) query. None when no key is configured."""
    key = api_key if api_key is not None else os.getenv("PERPLEXITY_API_KEY", "")
    if not key:
        return None
    res = ProbeResult(engine="perplexity", question=question,
                      asked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))
    try:
        r = requests.post(
            PERPLEXITY_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": PERPLEXITY_MODEL,
                  "messages": [{"role": "user", "content": question}]},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
        return res

    urls = [u for u in (data.get("citations") or []) if isinstance(u, str)]
    urls += [s.get("url", "") for s in (data.get("search_results") or []) if isinstance(s, dict)]
    try:
        res.answer_text = data["choices"][0]["message"]["content"] or ""
    except Exception:
        res.answer_text = ""
    res.cited_domains = _dedupe_domains(urls)
    res.brands = _score_brands(brands, urls, res.answer_text)
    return res


def _iter_annotations(payload) -> list[dict]:
    """
    Collect every annotation dict from an OpenAI Responses payload.

    Deliberately a recursive walk: citations nest as
    output[].content[].annotations[], but that nesting has moved between SDK
    versions. Walking keeps this working instead of silently reporting zero
    citations after an SDK bump.
    """
    found: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "annotations" and isinstance(v, list):
                    found.extend(a for a in v if isinstance(a, dict))
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def openai_client():
    """An OpenAI client, or None when unavailable. Never raises."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    except Exception:
        return None


def probe_chatgpt(question: str, brands: list[Brand], client=None) -> ProbeResult | None:
    """
    One web-grounded ChatGPT answer via the Responses API + web_search tool.

    Caveat worth repeating from scripts/chatgpt_monitor.py: the API with
    web_search is a PROXY for chatgpt.com, not the same surface. Treat the
    numbers as directional, not as what a consumer literally sees.
    """
    cl = client if client is not None else openai_client()
    if cl is None:
        return None
    res = ProbeResult(engine="chatgpt", question=question,
                      asked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))
    try:
        resp = cl.responses.create(model=CHATGPT_MODEL,
                                   tools=[{"type": "web_search"}], input=question)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
        return res

    try:
        payload = resp.model_dump()
    except Exception:
        try:
            payload = json.loads(resp.model_dump_json())
        except Exception:
            payload = {}

    urls = [a["url"] for a in _iter_annotations(payload)
            if a.get("type") in (None, "url_citation") and a.get("url")]
    try:
        res.answer_text = resp.output_text or ""
    except Exception:
        res.answer_text = ""
    res.cited_domains = _dedupe_domains(urls)
    res.brands = _score_brands(brands, urls, res.answer_text)
    return res


ENGINES = {"perplexity": probe_perplexity, "chatgpt": probe_chatgpt}


def probe(engine: str, question: str, brands: list[Brand], **kw) -> ProbeResult | None:
    fn = ENGINES.get(engine)
    if fn is None:
        raise ValueError(f"unknown engine {engine!r} (have: {sorted(ENGINES)})")
    return fn(question, brands, **kw)
