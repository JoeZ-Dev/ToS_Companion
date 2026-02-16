import time
import pytest

websocket = pytest.importorskip("websocket")

from momentum_companion.clients.schwab_stream import SchwabStreamClient


def test_stream_freshness():
    client = SchwabStreamClient({"streamerSocketUrl": "", "schwabClientCustomerId": "", "schwabClientCorrelId": "", "schwabClientChannel": "", "schwabClientFunctionId": "", "access_token": ""}, lambda x: None)  # type: ignore[arg-type]
    # manually set last timestamp
    client._last_ts_ms = int(time.time() * 1000) - 4000  # type: ignore[attr-defined]
    assert client.is_fresh(int(time.time() * 1000)) is True
    client._last_ts_ms = int(time.time() * 1000) - 6000  # type: ignore[attr-defined]
    assert client.is_fresh(int(time.time() * 1000)) is False
