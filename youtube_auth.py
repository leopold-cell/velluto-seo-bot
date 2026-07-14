#!/usr/bin/env python3
"""
One-time setup — run LOCALLY to mint a YouTube upload refresh token so the reel
pipeline can cross-post Shorts.

Prerequisites (once, in Google Cloud Console for the project that owns the
Velluto YouTube channel):
  1. Enable "YouTube Data API v3".
  2. APIs & Services → Credentials → Create → OAuth 2.0 Client ID → Desktop App.
  3. On the OAuth consent screen add the scope .../auth/youtube.upload and add
     your Google account as a test user (or publish the app).

Usage:
  python youtube_auth.py
Then set on the VPS (.env) / GitHub secrets:
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
(You can reuse GOOGLE_CLIENT_ID/SECRET only if that same client has the
YouTube scope + channel access; a dedicated YOUTUBE_* client is cleaner.)
"""
import http.server
import sys
import threading
import urllib.parse
import webbrowser

import requests

REDIRECT_URI = "http://localhost:8080"
SCOPE        = "https://www.googleapis.com/auth/youtube.upload"


def main():
    print("=" * 55)
    print("  Velluto YouTube Upload OAuth Setup")
    print("=" * 55)
    print("\nNeeds a Desktop OAuth client on a project with 'YouTube Data API v3'")
    print("enabled, on the Google account that owns the Velluto channel.\n")

    client_id     = input("Paste Client ID:     ").strip()
    client_secret = input("Paste Client Secret: ").strip()
    if not client_id or not client_secret:
        print("Error: both fields required.")
        sys.exit(1)

    auth_url = (
        "https://accounts.google.com/o/oauth2/auth"
        f"?client_id={urllib.parse.quote(client_id)}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        "&response_type=code"
        f"&scope={urllib.parse.quote(SCOPE)}"
        "&access_type=offline&prompt=consent"
    )
    code = [None]

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code[0] = q.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2 style='font-family:sans-serif;padding:40px'>"
                             b"&#10003; Authorized! Close this tab.</h2>")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("localhost", 8080), _Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    print("\nOpening browser for Google authorization...")
    webbrowser.open(auth_url)
    print("Waiting for authorization (120s timeout)...")
    threading.Event().wait  # noop keep import tidy
    import time
    for _ in range(120):
        if code[0]:
            break
        time.sleep(1)

    if not code[0]:
        print("\nError: no authorization code received. Try again.")
        sys.exit(1)

    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code[0], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code",
    }, timeout=15)
    tokens = r.json()
    if "refresh_token" not in tokens:
        print(f"\nError exchanging code: {tokens}")
        sys.exit(1)

    print("\n" + "=" * 55)
    print("  ✅ Success! Add to .env / GitHub secrets:")
    print("=" * 55)
    print(f"\nYOUTUBE_CLIENT_ID\n  {client_id}\n")
    print(f"YOUTUBE_CLIENT_SECRET\n  {client_secret}\n")
    print(f"YOUTUBE_REFRESH_TOKEN\n  {tokens['refresh_token']}\n")
    print("Then set YT_AUTOPOST=1 to arm real uploads.")
    print("=" * 55)


if __name__ == "__main__":
    main()
