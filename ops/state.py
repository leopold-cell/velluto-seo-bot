"""
State file helpers: atomic JSON read/write and the self-gating interval check.

The repo convention is that every scheduled script owns a state file and exits
early when it already ran, so a daily cron invocation is harmless. `gate_ok`
is that check, factored out of blog_review._gate_ok / seeding_targets.

Atomic writes matter here: the daily cron commits these files to git, so a
half-written JSON from an interrupted run would be committed and then fail to
parse on the next run.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from typing import Any


def today() -> _dt.date:
    return _dt.date.today()


def load_json(path: str, default: Any = None) -> Any:
    """Read JSON, returning `default` on missing file or unparseable content."""
    if not os.path.exists(path):
        return {} if default is None else default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def save_json(path: str, payload: Any) -> None:
    """
    Write JSON atomically: temp file in the same directory, then os.replace.
    A crash mid-write leaves the previous file intact rather than a truncated one.
    """
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def gate_ok(state_path: str, interval_days: int, force: bool = False,
            key: str = "last_run") -> tuple[bool, str]:
    """
    Should a periodic job run today?

    Returns (run, why). `force` always runs. No recorded run always runs.
    An unparseable date is treated as "never ran" rather than blocking forever.
    """
    if force:
        return True, "forced"
    state = load_json(state_path, {})
    last = state.get(key) if isinstance(state, dict) else None
    if not last:
        return True, "no previous run"
    try:
        last_d = _dt.date.fromisoformat(str(last)[:10])
    except Exception:
        return True, f"unreadable {key}={last!r}"
    age = (today() - last_d).days
    if age >= interval_days:
        return True, f"{age}d since last run (interval {interval_days}d)"
    return False, f"ran {age}d ago (interval {interval_days}d)"


def mark_run(state_path: str, key: str = "last_run", **extra: Any) -> None:
    """Record today's run in the state file, preserving other keys."""
    state = load_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    state[key] = today().isoformat()
    state.update(extra)
    save_json(state_path, state)
