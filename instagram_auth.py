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


def _pages_via_businesses(user_token: str) -> list:
    """Collect Pages reachable through the user's Business-Portfolios.

    Portfolio-owned assets (e.g. the Velluto page inside 'Velluto Website') don't
    appear in /me/accounts, so we enumerate businesses → owned_pages + client_pages.
    Requires the 'business_management' scope on the token. Returns [] on any failure.
    """
    out, seen = [], set()
    try:
        biz = requests.get(f"{GRAPH}/me/businesses",
                           params={"access_token": user_token}, timeout=30).json().get("data", [])
    except Exception:
        return out
    for b in biz:
        bid = b.get("id")
        if not bid:
            continue
        for edge in ("owned_pages", "client_pages"):
            try:
                data = requests.get(f"{GRAPH}/{bid}/{edge}", params={
                    "fields": "name,access_token,instagram_business_account",
                    "access_token": user_token}, timeout=30).json().get("data", [])
            except Exception:
                data = []
            for p in data:
                if p.get("id") and p["id"] not in seen:
                    seen.add(p["id"])
                    out.append(p)
    if out:
        print(f"   ✓ {len(out)} page(s) found via Business-Portfolios")
    return out


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

    # 2) resolve the page. Preferred: FB_PAGE_ID set in .env → fetch the page token
    # directly (bypasses /me/accounts entirely, which hides Business-Portfolio pages).
    fixed_id = os.getenv("FB_PAGE_ID", "").strip()
    if fixed_id:
        p = requests.get(f"{GRAPH}/{fixed_id}", params={
            "fields": "name,access_token,instagram_business_account",
            "access_token": ll}, timeout=30).json()
        if not p.get("access_token"):
            _die(f"could not get a Page token for FB_PAGE_ID={fixed_id} — are you an admin of it "
                 f"and did the token include 'business_management'? Response: {p}")
        page = p
    else:
        pages = requests.get(f"{GRAPH}/me/accounts", params={
            "fields": "name,access_token,instagram_business_account",
            "access_token": ll}, timeout=30).json().get("data", [])

        # Fallback: Pages owned by a Business-Portfolio (like "Velluto Website") often
        # do NOT surface in /me/accounts. Walk the businesses and collect their owned/
        # client pages — each carries its own page token + instagram_business_account.
        biz_pages = _pages_via_businesses(ll)
        seen = {p.get("id") for p in pages}
        pages += [p for p in biz_pages if p.get("id") not in seen]

        if not pages:
            _die("no Facebook Pages found. Easiest fix: set FB_PAGE_ID=117453561385428 in .env "
                 "and re-run (include the 'business_management' scope on the token).")
        if len(pages) == 1:
            page = pages[0]
        else:
            for i, p in enumerate(pages):
                print(f"   [{i}] {p.get('name')}  ({p.get('id')})")
            page = pages[int(input("Which page #? ").strip())]
    page_token, page_id = page["access_token"], page["id"]
    print(f"   ✓ page: {page.get('name')} ({page_id})")

    # 3) IG business account id on that page. Try the page token first, then the
    # long-lived user token (portfolio pages sometimes only answer to the user token).
    ig_id = ""
    last = {}
    for tok in (page_token, ll):
        resp = requests.get(f"{GRAPH}/{page_id}", params={
            "fields": "instagram_business_account", "access_token": tok}, timeout=30).json()
        last = resp
        ig_id = (resp.get("instagram_business_account") or {}).get("id")
        if ig_id:
            break

    if not ig_id:
        err = (last.get("error") or {}).get("message", "")
        if "pages_read_engagement" in err or "code" in str(last.get("error", {}).get("code", "")):
            _die("token is missing a granted permission. Re-generate it in the Graph Explorer "
                 "and make sure 'pages_read_engagement' + 'instagram_basic' are actually GRANTED "
                 "(approve them in the login popup), then verify with GET /me/permissions. "
                 f"Response: {last}")
        _die(f"no instagram_business_account linked to this Page. In Business-Suite the link "
             f"exists (velluto.cc), so this is almost always a token-scope issue. Response: {last}")

    upsert_env("IG_ACCESS_TOKEN", page_token)
    upsert_env("IG_USER_ID", ig_id)
    print(f"\n✅ IG-User-ID: {ig_id}")
    print(f"   IG_ACCESS_TOKEN + IG_USER_ID written to {ENV_PATH}")
    print("   (.env is gitignored — secrets stay local.)")


if __name__ == "__main__":
    main()
