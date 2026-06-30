#!/usr/bin/env python3
"""
One-time Instagram Graph API bootstrap.

Exchanges a short-lived User token (from the Graph API Explorer) for a long-lived
PAGE token, resolves the linked Instagram business-account id, and writes both to
.env as IG_ACCESS_TOKEN + IG_USER_ID. Page tokens derived from a long-lived user
token effectively don't expire.

Prereqs in .env:  FB_APP_ID, FB_APP_SECRET
Get the short token:  developers.facebook.com/tools/explorer → select your app →
  add permissions  instagram_basic, instagram_content_publish, pages_show_list,
  pages_read_engagement, business_management  → Generate Access Token.

Run:  python3 instagram_auth.py
"""
import os
import sys

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE, ".env")
load_dotenv(ENV_PATH, override=True)

GRAPH = "https://graph.facebook.com/v21.0"
APP_ID = os.getenv("FB_APP_ID", "")
APP_SECRET = os.getenv("FB_APP_SECRET", "")


def _die(msg: str):
    print(f"✗ {msg}")
    sys.exit(1)


def upsert_env(key: str, value: str):
    lines = []
    if os.path.exists(ENV_PATH):
        lines = open(ENV_PATH, encoding="utf-8").read().splitlines()
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    open(ENV_PATH, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def main():
    print("📸 Velluto Instagram — Graph API bootstrap\n" + "=" * 44)
    if not APP_ID or not APP_SECRET:
        _die("FB_APP_ID / FB_APP_SECRET missing in .env — add them (App → Settings → Basic) and re-run.")

    short = input("\nPaste the short-lived User token from the Graph API Explorer:\n> ").strip()
    if not short:
        _die("no token provided")

    # 1) short-lived → long-lived user token
    r = requests.get(f"{GRAPH}/oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": APP_ID,
        "client_secret": APP_SECRET, "fb_exchange_token": short}, timeout=30)
    ll = r.json().get("access_token")
    if not ll:
        _die(f"token exchange failed: {r.text[:300]}")
    print("   ✓ long-lived user token obtained")

    # 2) list pages → pick → long-lived page token
    pages = requests.get(f"{GRAPH}/me/accounts",
                         params={"access_token": ll}, timeout=30).json().get("data", [])
    if not pages:
        _die("no Facebook Pages found for this token (is the Page in this app/business + you admin?)")
    if len(pages) == 1:
        page = pages[0]
    else:
        for i, p in enumerate(pages):
            print(f"   [{i}] {p.get('name')}  ({p.get('id')})")
        page = pages[int(input("Which page #? ").strip())]
    page_token, page_id = page["access_token"], page["id"]
    print(f"   ✓ page: {page.get('name')} ({page_id})")

    # 3) IG business account id on that page
    ig = requests.get(f"{GRAPH}/{page_id}", params={
        "fields": "instagram_business_account", "access_token": page_token}, timeout=30).json()
    ig_id = (ig.get("instagram_business_account") or {}).get("id")
    if not ig_id:
        _die(f"no instagram_business_account linked to this Page — connect the IG account to "
             f"this FB Page first (IG app → Settings → linked Page). Response: {ig}")

    upsert_env("IG_ACCESS_TOKEN", page_token)
    upsert_env("IG_USER_ID", ig_id)
    print(f"\n✅ IG-User-ID: {ig_id}")
    print(f"   IG_ACCESS_TOKEN + IG_USER_ID written to {ENV_PATH}")
    print("   (.env is gitignored — secrets stay local.)")


if __name__ == "__main__":
    main()
