"""
DataForSEO HTTP wrapper with a shared, per-project spend ledger.

Why this exists
---------------
DataForSEO bills PER TASK against ONE account balance. Before this module the
accounting was split and incomplete:

  * keyword_research.DAILY_TASK_CAP counts only `search_volume` tasks, and it
    stores its counter inside data/keyword_volume_cache.json.
  * research/serp_fetcher.py posts directly with requests and is counted
    nowhere at all.

So the balance was the only real shared limit, guarded after the fact by
resource_monitor.py's DATAFORSEO_MIN_BALANCE check. That is fine for one
project. With a second project spending from the same balance it is not: a runaway
loop in project B drains the account, and project A's lookups then silently
degrade to volume 0 — which every caller "handles gracefully", i.e. invisibly.

This module gives every call site one ledger and lets a project be capped
independently, so a new project can never spend the shared balance out from
under the pipeline that pays for it.

Caps are opt-in per project, read from `<PROJECT>_DATAFORSEO_TASK_CAP`:
  HERMES_DATAFORSEO_TASK_CAP=10   → hermes blocked past 10 tasks/day
  (velluto has no ops-level cap; its existing per-endpoint caps still apply,
   so wiring it in here records spend without changing any behaviour)
"""
from __future__ import annotations

import datetime as _dt
import os

import requests

from ops.state import load_json, save_json

BASE = "https://api.dataforseo.com/v3"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_PATH = os.path.join(ROOT, "data", "dataforseo_spend.json")

# Published per-task prices, for estimation and for the ledger's usd column.
# Source: dataforseo.com/pricing — keep in sync when they change.
UNIT_USD = {
    "serp/google/organic/live/advanced":        0.002,
    "keywords_data/google_ads/search_volume/live": 0.05,
    "on_page/instant_pages":                    0.00015,
    "business_data/business_listings/search/live": 0.012,
}
DEFAULT_UNIT_USD = 0.002


def credentials() -> tuple[str, str]:
    return os.getenv("DATAFORSEO_LOGIN", ""), os.getenv("DATAFORSEO_PASSWORD", "")


def have_credentials() -> bool:
    login, password = credentials()
    return bool(login and password)


def unit_usd(path: str) -> float:
    return UNIT_USD.get(path.strip("/"), DEFAULT_UNIT_USD)


def project_cap(project: str) -> int | None:
    """Daily task cap for a project, or None when uncapped."""
    raw = os.getenv(f"{project.upper()}_DATAFORSEO_TASK_CAP")
    if raw is None or raw == "":
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def _today() -> str:
    return _dt.date.today().isoformat()


def _read_ledger() -> dict:
    led = load_json(LEDGER_PATH, {})
    if not isinstance(led, dict) or led.get("date") != _today():
        # New day: reset counters. Keep yesterday's totals for the report.
        return {"date": _today(), "projects": {}, "previous": led if isinstance(led, dict) else {}}
    led.setdefault("projects", {})
    return led


def spent_today(project: str) -> tuple[int, float]:
    """(tasks, usd) recorded for `project` today."""
    entry = _read_ledger()["projects"].get(project) or {}
    return int(entry.get("tasks", 0)), float(entry.get("usd", 0.0))


def reserve(project: str, n_tasks: int, path: str) -> tuple[int, str]:
    """
    Claim up to `n_tasks` for `project`, recording them in the ledger.

    Returns (granted, why). `granted` may be fewer than requested, or 0 when the
    project's cap is exhausted — callers must handle a partial grant the way
    keyword_research already handles its cap (skip the remainder, don't fail).
    Uncapped projects always get the full request; the tasks are still recorded.
    """
    if n_tasks <= 0:
        return 0, "nothing requested"
    led = _read_ledger()
    entry = led["projects"].setdefault(project, {"tasks": 0, "usd": 0.0})
    used = int(entry.get("tasks", 0))

    cap = project_cap(project)
    granted = n_tasks if cap is None else max(0, min(n_tasks, cap - used))
    why = "uncapped" if cap is None else f"{used + granted}/{cap} tasks used today"
    if granted == 0:
        return 0, f"cap reached ({used}/{cap})"

    entry["tasks"] = used + granted
    entry["usd"] = round(float(entry.get("usd", 0.0)) + granted * unit_usd(path), 5)
    save_json(LEDGER_PATH, led)
    return granted, why


def post(path: str, payload: list | dict, project: str = "velluto",
         timeout: int = 45, count_tasks: int | None = None) -> list | None:
    """
    POST to DataForSEO and return the `tasks` array, or None on any failure.

    No exception bubbles up — every caller in this repo treats None as "no data".
    `count_tasks` defaults to len(payload) for a list body, since DataForSEO
    bills one task per array element.
    """
    login, password = credentials()
    if not (login and password):
        return None

    n = count_tasks if count_tasks is not None else (len(payload) if isinstance(payload, list) else 1)
    granted, why = reserve(project, n, path)
    if granted < n:
        print(f"   ⚠️  DataForSEO cap for '{project}': {why} — "
              f"requested {n} task(s), granted {granted}")
    if granted == 0:
        return None

    try:
        r = requests.post(f"{BASE}/{path.strip('/')}", json=payload,
                          auth=(login, password), timeout=timeout)
        r.raise_for_status()
        return r.json().get("tasks") or []
    except Exception as e:
        print(f"      ⚠️  DataForSEO {path} failed: {e}")
        return None


def summary() -> str:
    """One-line spend summary for the daily report."""
    led = _read_ledger()
    parts = [f"{p}: {v.get('tasks', 0)} tasks / ${v.get('usd', 0.0):.4f}"
             for p, v in sorted(led["projects"].items())]
    return f"DataForSEO {led['date']} — " + ("; ".join(parts) if parts else "no spend")
