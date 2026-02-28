from __future__ import annotations

import httpx

from momentum_companion.clients.schwab_rest import SchwabRestClient


class _DummyRest(SchwabRestClient):
    def __init__(self) -> None:
        super().__init__("https://api.test", lambda: "tok", client=httpx.Client())
        self.last_params = None

    def _request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        self.last_params = kwargs.get("params", {})
        return httpx.Response(200, request=httpx.Request(method, url), json={})


def test_pricehistory_range_omits_period_params():
    client = _DummyRest()
    client.fetch_price_history("CDIO", start_ms=1000, end_ms=2000, freq="1m")
    assert client.last_params is not None
    assert "startDate" in client.last_params and "endDate" in client.last_params
    assert client.last_params.get("periodType") == "day"
    assert client.last_params.get("period") == 1


def test_pricehistory_period_omits_explicit_range():
    client = _DummyRest()
    client.fetch_price_history("CDIO", start_ms=None, end_ms=None, freq="1m")
    assert client.last_params is not None
    assert "periodType" in client.last_params and "period" in client.last_params
    assert "startDate" not in client.last_params and "endDate" not in client.last_params
