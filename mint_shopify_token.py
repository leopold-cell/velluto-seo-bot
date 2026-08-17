#!/usr/bin/env python3
"""
Mint a short-lived Shopify Admin API access token via the client-credentials grant
and print ONLY the token to stdout.

Shopify's current auth model (https://shopify.dev/docs/apps/build/authentication-
authorization/client-secrets) issues ~24h tokens from client_id + client_secret —
there is no static token anymore. run.sh mints a fresh one each run and exports it:

    export SHOPIFY_TOKEN="$(python3 mint_shopify_token.py)"

so every downstream script (which reads SHOPIFY_TOKEN from the env) gets a valid
token. Requires in .env:  SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET  (+ SHOPIFY_STORE).
Falls back to a static SHOPIFY_TOKEN if client creds are absent (backward compat).
Errors go to stderr so stdout stays clean for capture.
"""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)


def mint() -> str:
    """Return a fresh Admin API token, or the static one if client creds are absent.

    Exposed as a function so seo_bot can call it directly at import time. Every
    script that imports seo_bot for SHOPIFY_HEADERS then works when run by hand,
    not only when started by run.sh — fifteen of them did not, and each failed
    with an unexplained 401.
    """
    store = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
    cid = os.getenv("SHOPIFY_CLIENT_ID", "")
    csec = os.getenv("SHOPIFY_CLIENT_SECRET", "")
    static = os.getenv("SHOPIFY_TOKEN", "")

    if not (cid and csec):
        sys.stderr.write("mint_shopify_token: SHOPIFY_CLIENT_ID/SECRET missing — "
                         "using static SHOPIFY_TOKEN if any\n")
        return static
    try:
        r = requests.post(
            f"https://{store}/admin/oauth/access_token",
            data={"grant_type": "client_credentials", "client_id": cid, "client_secret": csec},
            timeout=20,
        )
        if r.status_code != 200:
            sys.stderr.write(f"mint_shopify_token: HTTP {r.status_code}: {r.text[:200]}\n")
            return static
        return r.json().get("access_token", "") or static
    except Exception as e:
        sys.stderr.write(f"mint_shopify_token: {e}\n")
        return static


if __name__ == "__main__":
    sys.stdout.write(mint())
