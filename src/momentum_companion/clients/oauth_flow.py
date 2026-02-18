from __future__ import annotations

import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

import httpx
import webbrowser

SCHWAB_AUTHORIZE_URL = "https://api.schwabapi.com/v1/oauth/authorize"
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
BOUNCE_REDIRECT_URI = "https://companion-auth.p3l.co/callback"
LOCAL_OAUTH_PORT = 17500
LOCAL_REDIRECT_URI = f"http://127.0.0.1:{LOCAL_OAUTH_PORT}/callback"


class CallbackServer:
    def __init__(self, expected_state: str) -> None:
        self._code: Optional[str] = None
        self._state: Optional[str] = None
        self._error: Optional[str] = None
        self._expected_state = expected_state
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        handler = self._build_handler()
        self._server = HTTPServer(("127.0.0.1", LOCAL_OAUTH_PORT), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=1)

    def wait(self, timeout: float = 180.0) -> tuple[Optional[str], Optional[str], Optional[str]]:
        start = time.time()
        while time.time() - start < timeout:
            if self._error or self._code:
                break
            time.sleep(0.1)
        return self._code, self._state, self._error

    def _build_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                qs = parse_qs(parsed.query)
                outer._code = qs.get("code", [None])[0]
                outer._state = qs.get("state", [None])[0]
                if outer._state != outer._expected_state:
                    outer._error = "state_mismatch"
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"You can close this window.")

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        return Handler


class OAuthFlow:
    def __init__(self, client_id: str, client_secret: str, scope: str = "readonly") -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope

    def interactive_login(self) -> dict:
        state = secrets.token_hex(16)
        # Register with bounce
        register_url = BOUNCE_REDIRECT_URI.rsplit("/", 1)[0] + "/register"
        resp = httpx.post(register_url, json={"state": state, "local_redirect": LOCAL_REDIRECT_URI}, timeout=10.0)
        if resp.status_code != 200:
            raise RuntimeError("Failed to register state with companion-auth server.")

        auth_params = {
            "client_id": self.client_id,
            "redirect_uri": BOUNCE_REDIRECT_URI,
            "response_type": "code",
            "state": state,
            "scope": self.scope,
        }
        auth_url = f"{SCHWAB_AUTHORIZE_URL}?{urlencode(auth_params)}"

        server = CallbackServer(state)
        server.start()
        webbrowser.open(auth_url)

        code, returned_state, error = server.wait(timeout=180.0)
        server.stop()
        if error:
            raise RuntimeError(f"OAuth error: {error}")
        if not code or returned_state != state:
            raise RuntimeError("OAuth login failed or state mismatch.")
        return self._exchange_code(code)

    def _exchange_code(self, code: str) -> dict:
        auth = httpx.BasicAuth(self.client_id, self.client_secret)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": BOUNCE_REDIRECT_URI,
        }
        resp = httpx.post(SCHWAB_TOKEN_URL, data=data, headers=headers, auth=auth, timeout=15.0)
        resp.raise_for_status()
        body = resp.json()
        expires_in = body.get("expires_in", 1800)
        body["expires_at"] = time.time() + expires_in - 60
        return body

    def refresh(self, refresh_token: str) -> dict:
        auth = httpx.BasicAuth(self.client_id, self.client_secret)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        resp = httpx.post(SCHWAB_TOKEN_URL, data=data, headers=headers, auth=auth, timeout=10.0)
        resp.raise_for_status()
        body = resp.json()
        expires_in = body.get("expires_in", 1800)
        body["expires_at"] = time.time() + expires_in - 60
        return body
