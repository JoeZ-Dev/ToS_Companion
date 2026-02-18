import threading
import time

import pytest

from momentum_companion.clients.oauth_flow import OAuthFlow, LOCAL_REDIRECT_URI, BOUNCE_REDIRECT_URI


def test_interactive_login_loopback(monkeypatch):
    # Stub register and token endpoints
    state_holder = {}

    class FakeResp:
        def __init__(self, status_code=200, data=None):
            self.status_code = status_code
            self._data = data or {}

        def json(self):
            return self._data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")

    def fake_post(url, json=None, data=None, headers=None, timeout=10.0, auth=None):
        if url.endswith("/register"):
            state_holder["state"] = json["state"]
            return FakeResp(200, {"ok": True})
        if "oauth/token" in url:
            return FakeResp(
                200,
                {
                    "access_token": "tok",
                    "refresh_token": "rtok",
                    "expires_in": 1800,
                },
            )
        raise RuntimeError("unexpected url")

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("webbrowser.open", lambda url: None)

    # Avoid binding sockets in test; fake callback server
    class FakeCallback:
        def __init__(self, expected_state):
            self.expected_state = expected_state

        def start(self):
            return None

        def stop(self):
            return None

        def wait(self, timeout=180.0):
            return "abc", self.expected_state, None

    monkeypatch.setattr("momentum_companion.clients.oauth_flow.CallbackServer", lambda state: FakeCallback(state))

    flow = OAuthFlow("cid", "secret")
    tokens = flow.interactive_login()
    assert tokens["access_token"] == "tok"
    assert tokens["refresh_token"] == "rtok"
