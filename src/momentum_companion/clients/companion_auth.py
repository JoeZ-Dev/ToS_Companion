from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx


class CompanionAuthError(RuntimeError):
    """A redacted companion_auth failure safe to surface to the UI."""


class CompanionAuthClient:
    """Trusted server-to-server adapter for the existing token owner."""

    def __init__(
        self,
        base_url: str | None = None,
        shared_secret: str | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("AUTH_HELPER_URL") or ""
        ).rstrip("/")
        self._shared_secret = (
            shared_secret
            if shared_secret is not None
            else os.environ.get("INTERNAL_AUTH_SECRET", "")
        )
        self._client = client or httpx.Client(
            timeout=10.0, follow_redirects=False, trust_env=False
        )

    def start_authorization(self) -> dict[str, Any]:
        response = self._request("POST", "/oauth/authorize")
        body = self._json(response)
        url = str(body.get("authorization_url") or "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.schwabapi.com":
            raise CompanionAuthError("companion_auth returned an invalid authorization URL")
        flow_id = str(body.get("flow_id") or "")
        if not flow_id:
            raise CompanionAuthError("companion_auth returned an incomplete authorization request")
        return {
            "authorization_url": url,
            "flow_id": flow_id,
            "expires_at": body.get("expires_at"),
        }

    def authorization_status(self, flow_id: str) -> dict[str, Any]:
        if not flow_id or "/" in flow_id:
            raise CompanionAuthError("invalid authorization request")
        response = self._request("GET", f"/oauth/status/{flow_id}")
        body = self._json(response)
        status = str(body.get("status") or "failed")
        if status not in {"waiting", "verifying", "authorized", "failed", "expired"}:
            raise CompanionAuthError("companion_auth returned an invalid authorization status")
        result = {"status": status, "expires_at": body.get("expires_at")}
        if status in {"failed", "expired"}:
            result["error"] = str(body.get("error") or "Authorization failed. Please retry.")
        return result

    def _request(self, method: str, path: str) -> httpx.Response:
        if not self.base_url or not self._shared_secret:
            raise CompanionAuthError("companion_auth is not configured")
        try:
            response = self._client.request(
                method,
                self.base_url + path,
                headers={"X-Internal-Auth": self._shared_secret},
            )
        except Exception as exc:
            raise CompanionAuthError("companion_auth is unavailable") from exc
        if response.status_code == 401:
            raise CompanionAuthError("companion_auth rejected the trusted service request")
        if response.status_code >= 400:
            raise CompanionAuthError("companion_auth is unavailable")
        return response

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except Exception as exc:
            raise CompanionAuthError("companion_auth returned an invalid response") from exc
        if not isinstance(body, dict):
            raise CompanionAuthError("companion_auth returned an invalid response")
        return body
