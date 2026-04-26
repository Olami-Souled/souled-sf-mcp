"""
One-time OAuth 2.0 Authorization Code flow helper for Salesforce.

Opens your browser, you click "Allow" once, and this script prints a refresh token
you can paste into Railway env vars.

Usage:
    export SF_CLIENT_ID=3MVG9...
    export SF_CLIENT_SECRET=...
    export SF_INSTANCE_URL=https://jewishunityinternational.my.salesforce.com
    python scripts/get_refresh_token.py

The script:
  1. Starts a local HTTP server on port 8888 to catch the OAuth callback
  2. Opens your default browser to the Salesforce OAuth authorize URL
  3. You log into SF (if not already) and click "Allow"
  4. SF redirects to http://localhost:8888/callback?code=...
  5. Script exchanges the code for an access token + refresh token
  6. Prints the refresh token
  7. Shuts down cleanly

Output (copy the REFRESH_TOKEN line into Railway):
    SF_REFRESH_TOKEN=<long_token>
    SF_INSTANCE_URL=<your instance url>
"""
import base64
import hashlib
import os
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

import requests

CALLBACK_PORT = 8888
CALLBACK_PATH = "/callback"


class CallbackHandler(BaseHTTPRequestHandler):
    """Captures the OAuth redirect back from Salesforce."""

    # We stash the received code on the class so the main thread can pick it up
    code: str | None = None
    error: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        qs = parse_qs(parsed.query)
        if "code" in qs:
            CallbackHandler.code = qs["code"][0]
            body = b"<html><body><h2>OK! You can close this tab and go back to the terminal.</h2></body></html>"
        elif "error" in qs:
            CallbackHandler.error = f"{qs.get('error', [''])[0]}: {qs.get('error_description', [''])[0]}"
            body = f"<html><body><h2>Error</h2><pre>{CallbackHandler.error}</pre></body></html>".encode()
        else:
            CallbackHandler.error = "No code in callback"
            body = b"<html><body><h2>Error: no code received</h2></body></html>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Silence default access log
        pass


def main():
    client_id = os.environ.get("SF_CLIENT_ID")
    client_secret = os.environ.get("SF_CLIENT_SECRET")
    instance_url = os.environ.get("SF_INSTANCE_URL")

    if not client_id or not client_secret:
        print("ERROR: Set SF_CLIENT_ID and SF_CLIENT_SECRET env vars first.", file=sys.stderr)
        print("Optionally SF_INSTANCE_URL (defaults to login.salesforce.com).", file=sys.stderr)
        sys.exit(1)

    login_host = instance_url or "https://login.salesforce.com"

    # PKCE: required when the Connected App has "Require Proof Key for Code
    # Exchange" enabled. Cheap to always include, so we do.
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")

    # Step 1: Start local HTTP server to catch callback. ThreadingHTTPServer so
    # one stuck connection doesn't block subsequent requests (the redirect
    # response can race with the same browser opening dev-tools or favicon
    # requests on the same port).
    server = ThreadingHTTPServer(("127.0.0.1", CALLBACK_PORT), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Listening for callback on http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}")

    # Step 2: Build OAuth authorize URL and open browser
    authorize_url = f"{login_host}/services/oauth2/authorize?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}",
        "scope": "api refresh_token offline_access",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # Prompt=login forces fresh login (optional, safer)
        "prompt": "login consent",
    })
    print("\nOpening browser to authorize the app...")
    print(f"If it doesn't open, paste this URL into your browser:\n  {authorize_url}\n")
    webbrowser.open(authorize_url)

    # Step 3: Wait for callback
    print("Waiting for you to click Allow in the browser...")
    import time
    for _ in range(300):  # wait up to 5 min
        if CallbackHandler.code or CallbackHandler.error:
            break
        time.sleep(1)

    server.shutdown()

    if CallbackHandler.error:
        print(f"\nOAuth error: {CallbackHandler.error}", file=sys.stderr)
        sys.exit(1)
    if not CallbackHandler.code:
        print("\nTimeout waiting for OAuth callback", file=sys.stderr)
        sys.exit(1)

    code = CallbackHandler.code
    print(f"\nGot authorization code (length {len(code)})")

    # Step 4: Exchange code for tokens
    print("Exchanging code for tokens...")
    token_url = f"{login_host}/services/oauth2/token"
    resp = requests.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}",
            "code_verifier": code_verifier,
        },
        timeout=30,
    )

    if not resp.ok:
        print(f"Token exchange failed: HTTP {resp.status_code}", file=sys.stderr)
        print(resp.text, file=sys.stderr)
        sys.exit(1)

    body = resp.json()
    refresh_token = body.get("refresh_token")
    access_token = body.get("access_token")
    actual_instance = body.get("instance_url")

    if not refresh_token:
        print("ERROR: No refresh_token in response. Did you include 'refresh_token' scope?", file=sys.stderr)
        print("Full response:", body, file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 60)
    print("SUCCESS — paste these into Railway env vars:")
    print("=" * 60)
    print(f"SF_CLIENT_ID={client_id}")
    print(f"SF_CLIENT_SECRET={client_secret}")
    print(f"SF_REFRESH_TOKEN={refresh_token}")
    print(f"SF_INSTANCE_URL={actual_instance}")
    print("=" * 60)
    print("\n(Verify: access_token starts with)", access_token[:20] + "..." if access_token else "<none>")


if __name__ == "__main__":
    main()
