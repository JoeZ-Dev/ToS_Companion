from __future__ import annotations

import time
import threading
import os
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

from tools.auth_helper.tokens import save_tokens, default_token_path

AUTH_BASE = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"


def _basic_auth() -> str:
    cid = os.environ.get("SCHWAB_CLIENT_ID")
    cs = os.environ.get("SCHWAB_CLIENT_SECRET")
    if not cid or not cs:
        raise RuntimeError("Set SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET")
    token = base64.b64encode(f"{cid}:{cs}".encode()).decode()
    return f"Basic {token}"


DEFAULT_SCOPE = "readonly streamerapi trade"


def build_auth_url(state: str) -> str:
    params = {
        "client_id": os.environ["SCHWAB_CLIENT_ID"],
        "redirect_uri": os.environ.get("SCHWAB_REDIRECT_URI", "https://companion-auth.p3l.co/callback"),
        "response_type": "code",
        # Always request streaming + readonly + trading scopes; no override from client env.
        "scope": DEFAULT_SCOPE,
        "state": state,
    }
    return f"{AUTH_BASE}?{urlencode(params)}"


auth_holder = {"code": None, "state": None, "error": None}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        q = urlparse(self.path)
        if q.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(q.query)
        if "error" in params:
            auth_holder["error"] = params.get("error", ["unknown"])[0]
        else:
            auth_holder["code"] = params.get("code", [None])[0]
            auth_holder["state"] = params.get("state", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"You can close this window.")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def exchange_code(code: str) -> dict:
    headers = {
        "Authorization": _basic_auth(),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": os.environ.get("SCHWAB_REDIRECT_URI", "https://companion-auth.p3l.co/callback"),
    }
    resp = httpx.post(TOKEN_URL, data=data, headers=headers, timeout=30.0)
    resp.raise_for_status()
    body = resp.json()
    body["expires_at"] = int(time.time()) + int(body.get("expires_in", 1800)) - 60
    return body


def main() -> None:
    if not os.environ.get("SCHWAB_CLIENT_ID") or not os.environ.get("SCHWAB_CLIENT_SECRET"):
        raise SystemExit("Set SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET in env on homelab.")
    host = os.environ.get("AUTH_HELPER_BIND", "0.0.0.0")
    port = int(os.environ.get("AUTH_HELPER_PORT", "8765"))
    try:
        httpd = HTTPServer((host, port), CallbackHandler)
    except PermissionError:
        # Fallback to localhost binding if broad bind is blocked.
        host = "127.0.0.1"
        httpd = HTTPServer((host, port), CallbackHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    state = "AUTH_HELPER_STATE"
    print("Open this URL and complete Schwab login/consent:\n")
    print(build_auth_url(state))
    print("\nWaiting for OAuth redirect to /callback ...")
    start = time.time()
    while time.time() - start < 180:
        if auth_holder["error"]:
            raise SystemExit(f"OAuth error: {auth_holder['error']}")
        if auth_holder["code"]:
            break
        time.sleep(0.25)
    httpd.shutdown()
    if not auth_holder["code"]:
        raise SystemExit("Timed out waiting for OAuth redirect.")
    if auth_holder["state"] != state:
        raise SystemExit("State mismatch; aborting.")
    tokens = exchange_code(auth_holder["code"])
    save_tokens(default_token_path(), tokens)
    print(f"Saved tokens to {default_token_path()}")


if __name__ == "__main__":
    main()
