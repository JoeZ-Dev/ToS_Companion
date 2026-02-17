from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Tuple

from tools.auth_helper.tokens import ensure_access_token, default_token_path


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.startswith("/health"):
            _json_response(self, 200, {"ok": True})
            return
        if self.path.startswith("/access_token"):
            try:
                tokens = ensure_access_token()
                _json_response(
                    self,
                    200,
                    {
                        "access_token": tokens["access_token"],
                        "expires_at": tokens.get("expires_at"),
                        "source": tokens.get("source", "homelab"),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                _json_response(
                    self,
                    409,
                    {
                        "error": "AUTH_REQUIRED",
                        "message": "Run tools/auth_helper/bootstrap.py to perform OAuth.",
                        "detail": str(exc),
                        "token_path": str(default_token_path()),
                    },
                )
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def run_server() -> None:
    host = os.environ.get("AUTH_HELPER_BIND", "0.0.0.0")
    port = int(os.environ.get("AUTH_HELPER_PORT", "8766"))
    httpd = HTTPServer((host, port), AuthHandler)
    print(f"Auth Helper listening on {host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
