from __future__ import annotations

import json

from momentum_companion.clients.massive_fundamentals_client import MassiveFundamentalsClient


class _StubResp:
    def __init__(self, content: str, status_code: int = 200, elapsed: float = 0.0) -> None:
        self.content = content.encode() if isinstance(content, str) else content
        self.status_code = status_code
        self.elapsed = type("e", (), {"total_seconds": lambda self: elapsed})()

    def json(self) -> dict:
        return json.loads(self.content.decode())

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400


class _StubSession:
    def __init__(self, responses, urls=None) -> None:
        self._responses = responses
        self._urls = urls or []
        self.calls = 0

    def get(self, url, params=None):  # noqa: ANN001
        idx = self.calls
        self.calls += 1
        if self._urls:
            assert self._urls[idx] == url
        return self._responses[idx]


def test_float_fallback_on_bad_json(tmp_path, caplog) -> None:
    bad = _StubResp("xxxx", status_code=200, elapsed=0.01)
    client = MassiveFundamentalsClient("k", tmp_path, caplog)
    client._session = _StubSession([bad])  # type: ignore[attr-defined]
    data = client.fetch_float("SYM")
    assert data["status"] == "FAILURE"


def test_sanitize_no_api_key_in_logs(tmp_path, caplog) -> None:
    caplog.set_level("INFO")
    resp = _StubResp(json.dumps({"results": [{"short_interest": 1, "settlement_date": "2025-01-01"}]}))
    client = MassiveFundamentalsClient("SECRETKEY", tmp_path, caplog)
    client._session = _StubSession([resp])  # type: ignore[attr-defined]
    client.fetch_short_interest("SYM")
    assert not any("SECRETKEY" in rec.message for rec in caplog.records)


def test_404_text_body_maps_failure(tmp_path) -> None:
    resp1 = _StubResp("404 Not Found", status_code=404)
    client = MassiveFundamentalsClient("k", tmp_path, None)
    client._session = _StubSession(
        [resp1],
        urls=[
            f"{client.BASE_URL}{client.MASSIVE_FLOAT_PATH}",
        ],
    )  # type: ignore[attr-defined]
    data = client.fetch_float("SYM")
    assert data["status"] == "NOT_AVAILABLE"
    assert client._session.calls == 1  # type: ignore[attr-defined]


def test_not_available_cached(tmp_path) -> None:
    resp1 = _StubResp("404 Not Found", status_code=404)
    client = MassiveFundamentalsClient("k", tmp_path, None)
    client._session = _StubSession(
        [resp1],
        urls=[f"{client.BASE_URL}{client.MASSIVE_FLOAT_PATH}"],
    )  # type: ignore[attr-defined]
    data1 = client.fetch_float("SYM")
    assert data1["status"] == "NOT_AVAILABLE"
    # second call should hit cache (no new network calls)
    data2 = client.fetch_float("SYM")
    assert data2["status"] == "NOT_AVAILABLE"
    assert client._session.calls == 1  # type: ignore[attr-defined]
