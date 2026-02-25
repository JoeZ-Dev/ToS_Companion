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
    def __init__(self, responses) -> None:
        self._responses = responses
        self.calls = 0

    def get(self, url, params=None):  # noqa: ANN001
        resp = self._responses[self.calls]
        self.calls += 1
        return resp


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
    resp = _StubResp("404 Not Found", status_code=404)
    client = MassiveFundamentalsClient("k", tmp_path, None)
    client._session = _StubSession([resp])  # type: ignore[attr-defined]
    data = client.fetch_float("SYM")
    assert data["status"] == "FAILURE"
    assert client._session.calls == 1  # type: ignore[attr-defined]
