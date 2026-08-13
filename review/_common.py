"""
Shared helpers for the review/ package: paths, config, lazy Anthropic client,
guarded LLM completion (text + vision), and cost logging.

Everything degrades gracefully when ANTHROPIC_API_KEY is missing so the audit
can run in --dry-run mode without credentials.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load the repo .env so standalone entry points (blog_review.py) get the same
# environment seo_bot.py does. Imported before any review submodule reads getenv.
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(ROOT, ".env"), override=False)
except Exception:
    pass

REVIEW_DIR = os.path.join(ROOT, "output", "blog_review")
STATE_PATH = os.path.join(REVIEW_DIR, "state.json")

BLOG_HANDLE = "velluto-the-magazine"
SITE = "https://velluto-shop.com"

# Models and the guarded Claude client live in ops/llm.py so other projects can
# reuse them without importing seo_bot. Re-exported here so every review/* call
# site keeps importing them from review._common unchanged.
from ops.llm import (  # noqa: E402,F401
    HAIKU, SONNET, have_anthropic, parse_json_block, http_get,
)
from ops import llm as _llm  # noqa: E402

# Locales the bot localizes into (mirror seo_bot.SHOP_LOCALES).
SHOP_LOCALES = ["de", "nl", "fr", "es", "it", "da", "nb", "pl", "pt-PT", "sv"]


# ── config ────────────────────────────────────────────────────────────────────

def review_config() -> dict:
    """Read the `review:` block from config/publishing_rules.yml with defaults."""
    defaults = {
        "interval_days": 28,
        "ui_sample_size": 5,
        "dead_post_impressions_threshold": 10,
        "weak_post_impressions_threshold": 50,
        "low_ctr_pct": 1.0,
        "target_locales": SHOP_LOCALES,
    }
    try:
        import config_loader
        raw = config_loader._load("publishing_rules") or {}
        review = raw.get("review") or {}
        defaults.update({k: v for k, v in review.items() if v is not None})
    except Exception:
        pass
    return defaults


# ── Anthropic (lazy + guarded) ──────────────────────────────────────────────────
# have_anthropic / parse_json_block / http_get come from ops.llm (imported above).
# Only the Velluto-specific part stays here: cost logging into token_usage.json.
# ops.llm takes the logger as a parameter precisely so it never has to import
# seo_bot — that import is what would drag Shopify config into any other project.

def _log_cost(inp: int, out: int, model: str) -> None:
    """Record token usage via seo_bot.log_usage if available; never raise."""
    try:
        import seo_bot
        seo_bot.log_usage(inp, out, model=model)
    except Exception:
        pass


def complete(system: str, user: str, model: str = HAIKU, max_tokens: int = 800,
             images: list[dict] | None = None) -> str:
    """
    One guarded Claude call. `images` is a list of
    {"media_type": "image/png", "data": "<base64>"} for vision.
    Returns "" if no API key (so callers can no-op in dry-run).
    """
    return _llm.complete(system, user, model=model, max_tokens=max_tokens,
                         images=images, usage_logger=_log_cost)


# ── state / io ────────────────────────────────────────────────────────────────

def today() -> _dt.date:
    return _dt.date.today()


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH))
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    os.makedirs(REVIEW_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
