from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict
from urllib.parse import urlparse, parse_qs

STATE_TTL_SECONDS = 180


class StateStore:
    def __init__(self) -> None:
        self._store: Dict[str, tuple[str, float]] = {}

    def put(self, state: str, local_redirect: str) -> None:
        self._store[state] = (local_redirect, time.time() + STATE_TTL_SECONDS)

    def pop(self, state: str) -> str | None:
        entry = self._store.pop(state, None)
        if not entry:
            return None
        local_redirect, expires_at = entry
        if time.time() > expires_at:
            return None
        return local_redirect

    def cleanup(self) -> None:
        now = time.time()
        for key, (_, exp) in list(self._store.items()):
            if now > exp:
                self._store.pop(key, None)


store = StateStore()


def _json(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class BounceHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/register":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            _json(self, 400, {"error": "invalid_json"})
            return
        state = body.get("state")
        local_redirect = body.get("local_redirect")
        if not state or not local_redirect:
            _json(self, 400, {"error": "missing_state_or_redirect"})
            return
        if not local_redirect.startswith("http://127.0.0.1:") or not local_redirect.endswith("/callback"):
            _json(self, 400, {"error": "invalid_local_redirect"})
            return
        store.put(state, local_redirect)
        _json(self, 200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = parse_qs(parsed.query)
        state = qs.get("state", [None])[0]
        code = qs.get("code", [None])[0]
        if not state or not code:
            _json(self, 400, {"error": "missing_state_or_code"})
            return
        store.cleanup()
        local_redirect = store.pop(state)
        if not local_redirect:
            _json(self, 400, {"error": "state_expired"})
            return
        # Single-use redirect
        redirect_url = f"{local_redirect}?code={code}&state={state}"
        self.send_response(302)
        self.send_header("Location", redirect_url)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Suppress logging to avoid leaking query strings.
        return


def main() -> None:
    server = HTTPServer(("0.0.0.0", 8765), BounceHandler)
    print("Companion auth bounce server listening on 0.0.0.0:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()
