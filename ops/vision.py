"""
Playwright screenshot capture for the "look at a page and judge it" loop.

Extracted from review/ui_audit.py._screenshot. Degrades gracefully when
Playwright or Chromium is unavailable — an empty dict, never an exception, so
an audit step can no-op instead of failing a pipeline.

Note for callers hitting third-party sites: pass a modest `full_page=False` and
cap your request rate per domain. Never commit captured screenshots of sites
you don't own.
"""
from __future__ import annotations

import base64

# The viewports the Velluto UI audit has always used. Callers may override.
VIEWPORTS: dict[str, tuple[int, int]] = {"mobile": (390, 844), "desktop": (1440, 900)}


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def screenshot(url: str, viewports: dict[str, tuple[int, int]] | None = None,
               timeout_ms: int = 30000, settle_ms: int = 800,
               full_page: bool = True, log_prefix: str = "ui") -> dict[str, str]:
    """
    Render `url` at each viewport and return {viewport_name: base64_png}.

    Returns whatever succeeded — a partial dict is normal and useful. An empty
    dict means Playwright itself was unavailable or the browser failed to launch.
    """
    vps = viewports if viewports is not None else VIEWPORTS
    shots: dict[str, str] = {}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            for name, (w, h) in vps.items():
                page = browser.new_page(viewport={"width": w, "height": h},
                                        device_scale_factor=1)
                try:
                    page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                    page.wait_for_timeout(settle_ms)
                    png = page.screenshot(full_page=full_page)
                    shots[name] = base64.b64encode(png).decode("ascii")
                except Exception as e:
                    print(f"   ⚠️  {log_prefix}: screenshot {name} failed for {url}: {e}")
                finally:
                    page.close()
            browser.close()
    except Exception as e:
        print(f"   ⚠️  {log_prefix}: playwright unavailable: {e}")
    return shots


def as_image_blocks(shots: dict[str, str]) -> list[dict]:
    """Turn {name: base64_png} into the `images` list ops.llm.complete expects."""
    return [{"media_type": "image/png", "data": b64} for b64 in shots.values()]
