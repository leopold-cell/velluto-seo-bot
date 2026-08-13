"""
Guarded Claude client: lazy, key-optional, cost-logging.

Extracted verbatim from review/_common.py so a second project can call Claude
without importing seo_bot (3100 lines, module-level Shopify config + dotenv).
That is why cost logging is an INJECTED callable rather than a hard import:
Velluto passes seo_bot.log_usage and keeps writing token_usage.json unchanged,
while another project logs wherever it likes.

Everything degrades gracefully when ANTHROPIC_API_KEY is missing, so callers
can run in --dry-run mode without credentials.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

import requests

# Models — match the ids used across the codebase (seo_bot.py).
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"

_client = None

UsageLogger = Callable[[int, int, str], None]


def have_anthropic() -> bool:
    """True only if a key is set AND the anthropic SDK is importable."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def _anthropic():
    global _client
    if _client is None:
        from anthropic import Anthropic
        _client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def complete(system: str, user: str, model: str = HAIKU, max_tokens: int = 800,
             images: list[dict] | None = None,
             usage_logger: UsageLogger | None = None) -> str:
    """
    One guarded Claude call. `images` is a list of
    {"media_type": "image/png", "data": "<base64>"} for vision.
    Returns "" if no API key (so callers can no-op in dry-run).

    `usage_logger(input_tokens, output_tokens, model)` records cost. Failures in
    the logger never break the call — accounting must not take down a pipeline.
    """
    if not have_anthropic():
        return ""
    content: list[dict] = []
    for img in (images or []):
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]},
        })
    content.append({"type": "text", "text": user})
    resp = _anthropic().messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}],
    )
    if usage_logger is not None:
        try:
            usage_logger(resp.usage.input_tokens, resp.usage.output_tokens, model)
        except Exception:
            pass
    return "".join(getattr(b, "text", "") for b in resp.content).strip()


def parse_json_block(text: str) -> Any:
    """Best-effort extraction of a JSON object/array from an LLM response."""
    if not text:
        return None
    # strip ```json fences
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def http_get(url: str, timeout: int = 12,
             user_agent: str = "Velluto-Review/1.0 (+seo-audit)") -> requests.Response | None:
    """GET that never raises. Identify honestly — this hits third-party sites."""
    try:
        return requests.get(url, timeout=timeout, headers={"User-Agent": user_agent})
    except Exception:
        return None
