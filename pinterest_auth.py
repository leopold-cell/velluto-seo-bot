#!/usr/bin/env python3
"""
Velluto Pinterest — one-time OAuth bootstrap.

Run this ONCE to turn your Pinterest app credentials into a long-lived
refresh token, so pinterest_poster.py can mint a fresh access token on every
run and never breaks when the ~30-day access token expires.

You need (from the Pinterest Developer Portal → your app "claude2"):
  PINTEREST_APP_ID
  PINTEREST_APP_SECRET
  PINTEREST_REDIRECT_URI   # must EXACTLY match a redirect URI registered on
                           # the app (e.g. https://localhost/ or your site URL)

Put those three in .env (or export them), then:

  python3 pinterest_auth.py

The script prints an authorize URL. Open it in a browser where you are logged
into the Velluto Pinterest account, click "Give access", and you'll be
redirected to <redirect_uri>?code=XXXX&state=YYYY. Copy that full URL (or just
the code) back into the terminal. The script exchanges it for tokens and offers
to append PINTEREST_REFRESH_TOKEN to .env for you.

Refresh tokens are valid ~1 year; access tokens are minted from them per run.

Docs: https://developers.pinterest.com/docs/getting-started/connect-app/
"""

import os
import sys
import base64
import secrets
import urllib.parse

import requests
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)

APP_ID       = os.getenv("PINTEREST_APP_ID", "")
APP_SECRET   = os.getenv("PINTEREST_APP_SECRET", "")
REDIRECT_URI = os.getenv("PINTEREST_REDIRECT_URI", "https://localhost/")

# Same scopes pinterest_poster.py needs: read boards, read+write pins.
SCOPES = "boards:read,pins:read,pins:write,user_accounts:read"

AUTH_URL  = "https://www.pinterest.com/oauth/"
TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"


def _fail(msg: str) -> None:
    print(f"\n❌ {msg}")
    sys.exit(1)


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": APP_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def extract_code(raw: str) -> str:
    """Accept either a bare code or the full redirect URL pasted by the user."""
    raw = raw.strip()
    if raw.startswith("http"):
        qs = urllib.parse.urlparse(raw).query
        code = urllib.parse.parse_qs(qs).get("code", [""])[0]
        return code
    # Allow "code=XXduration" or just "XX"
    if raw.startswith("code="):
        return raw[len("code="):].split("&")[0]
    return raw


def exchange_code(code: str) -> dict:
    basic = base64.b64encode(f"{APP_ID}:{APP_SECRET}".encode()).decode()
    r = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code",
              "code": code,
              "redirect_uri": REDIRECT_URI},
        timeout=30,
    )
    if r.status_code != 200:
        _fail(f"token exchange failed: http_{r.status_code} {r.text[:300]}")
    return r.json()


def upsert_env(key: str, value: str) -> None:
    """Add or replace KEY=value in .env, preserving the rest of the file."""
    lines: list[str] = []
    found = False
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    print("📌 Velluto Pinterest — OAuth bootstrap")
    print("=" * 50)

    if not APP_ID or not APP_SECRET:
        _fail("PINTEREST_APP_ID / PINTEREST_APP_SECRET missing — add them to .env "
              "(Developer Portal → your app → settings) and re-run.")

    state = secrets.token_urlsafe(16)
    url = build_authorize_url(state)

    print("\n1) Make sure this redirect URI is registered on your app:")
    print(f"     {REDIRECT_URI}")
    print("   (Developer Portal → app → 'Redirect URIs'. Override via "
          "PINTEREST_REDIRECT_URI in .env if needed.)")
    print("\n2) Open this URL in a browser logged into the Velluto Pinterest "
          "account and click 'Give access':\n")
    print(f"     {url}\n")
    print("3) You'll be redirected to your redirect URI with ?code=... in it.")

    raw = input("\nPaste the full redirected URL (or just the code) here:\n> ").strip()
    if not raw:
        _fail("no code provided")

    code = extract_code(raw)
    if not code:
        _fail("could not find a 'code' in what you pasted")

    print("\n   Exchanging code for tokens…")
    tok = exchange_code(code)
    access  = tok.get("access_token", "")
    refresh = tok.get("refresh_token", "")
    if not refresh:
        _fail(f"no refresh_token in response: {tok}")

    print("\n✅ Success! Tokens received.")
    print(f"   access_token  (expires in {tok.get('expires_in','?')}s): {access[:18]}…")
    print(f"   refresh_token (valid ~1 year):                          {refresh[:18]}…")

    ans = input("\nAppend PINTEREST_APP_ID/SECRET/REFRESH_TOKEN to .env now? [y/N] ").strip().lower()
    if ans == "y":
        upsert_env("PINTEREST_APP_ID", APP_ID)
        upsert_env("PINTEREST_APP_SECRET", APP_SECRET)
        upsert_env("PINTEREST_REFRESH_TOKEN", refresh)
        print(f"   ✓ Written to {ENV_PATH}")
        print("   (.env is gitignored — these secrets stay local.)")
    else:
        print("\nAdd these to .env manually:")
        print(f"   PINTEREST_APP_ID={APP_ID}")
        print(f"   PINTEREST_APP_SECRET={APP_SECRET}")
        print(f"   PINTEREST_REFRESH_TOKEN={refresh}")

    print("\nDone. pinterest_poster.py will now refresh its own access token "
          "on every run — no more 30-day expiry.")


if __name__ == "__main__":
    main()
