#!/usr/bin/env python3
"""
One-time setup script — run this LOCALLY to get Google OAuth credentials
for the Search Console API.

Usage:
  python gsc_auth.py

You'll need OAuth2 credentials (Client ID + Secret) from Google Cloud Console:
  1. console.cloud.google.com → APIs & Services → Credentials
  2. Create Credentials → OAuth 2.0 Client ID → Desktop App
  3. Download JSON — paste the client_id and client_secret when prompted

After running, add the 3 printed values as GitHub secrets.
"""

import webbrowser, urllib.parse, http.server, threading, requests, sys


REDIRECT_URI = "http://localhost:8080"
SCOPE        = "https://www.googleapis.com/auth/webmasters.readonly"


def main():
    print("=" * 55)
    print("  Velluto GSC OAuth Setup")
    print("=" * 55)
    print()
    print("You need OAuth2 Desktop App credentials from Google Cloud:")
    print("  console.cloud.google.com → APIs & Services → Credentials")
    print("  → Create Credentials → OAuth 2.0 Client ID → Desktop App")
    print()

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
        "&access_type=offline"
        "&prompt=consent"
    )

    code = [None]

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code[0] = params.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2 style='font-family:sans-serif;padding:40px'>"
                             b"&#10003; Authorized! You can close this tab.</h2>")
        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("localhost", 8080), _Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print("\nOpening browser for Google authorization...")
    webbrowser.open(auth_url)
    print("Waiting for authorization (120s timeout)...")
    thread.join(timeout=120)

    if not code[0]:
        print("\nError: no authorization code received. Try again.")
        sys.exit(1)

    # Exchange code for tokens
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code":          code[0],
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    }, timeout=15)

    tokens = r.json()
    if "refresh_token" not in tokens:
        print(f"\nError exchanging code: {tokens}")
        sys.exit(1)

    print("\n" + "=" * 55)
    print("  ✅ Success! Add these 3 GitHub secrets:")
    print("=" * 55)
    print(f"\nGOOGLE_CLIENT_ID\n  {client_id}\n")
    print(f"GOOGLE_CLIENT_SECRET\n  {client_secret}\n")
    print(f"GOOGLE_REFRESH_TOKEN\n  {tokens['refresh_token']}\n")
    print("GitHub → Settings → Secrets and variables → Actions → New secret")
    print("=" * 55)


if __name__ == "__main__":
    main()
