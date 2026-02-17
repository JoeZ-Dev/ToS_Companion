import threading
import time

from momentum_companion.clients.token_provider import TokenProvider
from momentum_companion.clients.schwab_rest import SchwabRestClient


def test_token_refresh_singleflight(tmp_path):
    calls = {"count": 0}

    def refresh_cb(cache):
        calls["count"] += 1
        time.sleep(0.1)
        return {"access_token": "new", "expires_at": time.time() + 3600}

    provider = TokenProvider(refresh_callback=refresh_cb, token_path=tmp_path / "tokens.json")
    provider.set_access_token("old", expires_at=time.time() + 0.01)

    results = []

    def worker():
        results.append(provider())

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert calls["count"] == 1
    assert results == ["new", "new"]


class FakeResponse:
    def __init__(self, status_code, json_body=None):
        self.status_code = status_code
        self._json = json_body or {}
        self.headers = {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, responses):
        self._responses = responses
        self.calls = 0

    def request(self, method, url, headers=None, **kwargs):
        resp = self._responses[self.calls]
        self.calls += 1
        return resp


def test_rest_retries_on_401(tmp_path):
    provider = TokenProvider(token_path=tmp_path / "tokens.json")
    provider.set_access_token("token", expires_at=time.time() + 3600)
    responses = [FakeResponse(401), FakeResponse(200, {"ok": True})]
    client = FakeClient(responses)
    rest = SchwabRestClient(base_url="http://example.com", auth_token_provider=provider, client=client)
    result = rest.get_accounts()
    assert result == {"ok": True}
    assert client.calls == 2


def test_token_refresh_http(monkeypatch, tmp_path):
    provider = TokenProvider(token_path=tmp_path / "tokens.json")
    provider.set_access_token("old", expires_at=time.time() + 1)
    provider._token_cache["refresh_token"] = "rt"  # inject

    class FakeResp:
        def __init__(self):
            self._json = {"access_token": "new", "expires_in": 100, "refresh_token": "rt2"}

        def raise_for_status(self):
            return None

        def json(self):
            return self._json

    def fake_post(url, data=None, headers=None, timeout=10.0):
        return FakeResp()

    monkeypatch.setattr("httpx.post", fake_post)
    import os

    os.environ["SCHWAB_CLIENT_ID"] = "id"
    os.environ["SCHWAB_CLIENT_SECRET"] = "secret"
    new_tokens = provider.refresh()
    assert new_tokens["access_token"] == "new"
    assert provider._token_cache["refresh_token"] == "rt2"


def test_auth_helper_mode(monkeypatch):
    monkeypatch.setenv("AUTH_HELPER_URL", "http://helper")
    provider = TokenProvider()
    resp_data = {"access_token": "helper_tok", "expires_at": time.time() + 3600}

    class FakeResp:
        status_code = 200

        def json(self):
            return resp_data

    def fake_get(url, timeout=10.0):
        return FakeResp()

    monkeypatch.setattr("httpx.get", fake_get)
    token = provider()
    assert token == "helper_tok"


def test_auth_helper_requires_auth(monkeypatch):
    monkeypatch.setenv("AUTH_HELPER_URL", "http://helper")
    provider = TokenProvider(state_callback=lambda s: setattr(provider, "_state", s))

    class FakeResp:
        status_code = 401

        def json(self):
            return {}

    monkeypatch.setattr("httpx.get", lambda url, timeout=10.0: FakeResp())
    provider()
    assert getattr(provider, "_state", None) == "AUTH_REQUIRED"
