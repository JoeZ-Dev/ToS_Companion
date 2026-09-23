import json

import pytest

websocket = pytest.importorskip("websocket")

from momentum_companion.clients.schwab_stream import SchwabStreamClient


class FakeWS:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(json.loads(message))


def _info():
    return {
        "streamerSocketUrl": "wss://example",
        "schwabClientCustomerId": "c",
        "schwabClientCorrelId": "corr",
        "schwabClientChannel": "ch",
        "schwabClientFunctionId": "fn",
        "access_token": "tok",
    }


def test_multi_symbol_subscription_uses_one_l1_subs_request():
    client = SchwabStreamClient(_info(), lambda event: None)
    ws = FakeWS()
    client._connected = True
    client._ws = ws

    client.subscribe_level_one_symbols([" tops ", "AEHL", "TOPS"])

    assert len(ws.sent) == 1
    request = ws.sent[0]
    assert request["service"] == "LEVELONE_EQUITIES"
    assert request["parameters"]["keys"] == "AEHL,TOPS"
    assert "8" in request["parameters"]["fields"]


def test_raw_payload_callback_sees_payload_before_mapping():
    raw = []
    quotes = []
    client = SchwabStreamClient(
        _info(),
        quotes.append,
        raw_payload_callback=raw.append,
    )
    ws = FakeWS()
    client._ws = ws

    payload = {
        "data": [
            {
                "service": "LEVELONE_EQUITIES",
                "timestamp": 1710000000000,
                "content": [
                    {"key": "AEHL", "1": 3.1, "2": 3.2, "3": 3.15, "8": 10000}
                ],
            }
        ]
    }
    client._on_message(ws, json.dumps(payload))

    assert raw == [payload]
    assert quotes[-1]["symbol"] == "AEHL"


def test_unsubscribe_removes_symbol_from_reconnect_subscription_set():
    client = SchwabStreamClient(_info(), lambda event: None)
    client._level_one_symbols = {"AEHL", "TOPS"}

    client.unsubscribe("AEHL")

    assert client._level_one_symbols == {"TOPS"}


def test_level_one_activity_age_tracks_received_l1_payload(monkeypatch):
    client = SchwabStreamClient(_info(), lambda event: None)
    ws = FakeWS()
    client._ws = ws
    client._connected = True
    now = [100.0]
    monkeypatch.setattr("momentum_companion.clients.schwab_stream.time.monotonic", lambda: now[0])

    payload = {
        "data": [{
            "service": "LEVELONE_EQUITIES",
            "timestamp": 1710000000000,
            "content": [{"key": "AEHL", "3": 3.15}],
        }]
    }
    client._on_message(ws, json.dumps(payload))
    now[0] = 112.5

    assert client.seconds_since_last_level_one() == 12.5


def test_refresh_level_one_subscription_resends_full_symbol_set():
    client = SchwabStreamClient(_info(), lambda event: None)
    ws = FakeWS()
    client._ws = ws
    client._connected = True
    client._level_one_symbols = {"AEHL", "TOPS"}

    assert client.refresh_level_one_subscription() is True
    assert ws.sent[-1]["command"] == "SUBS"
    assert ws.sent[-1]["parameters"]["keys"] == "AEHL,TOPS"


def test_force_reconnect_closes_current_socket_and_starts_recovery(monkeypatch):
    class ClosingWS(FakeWS):
        def __init__(self):
            super().__init__()
            self.closed = False

        def close(self):
            self.closed = True

    client = SchwabStreamClient(_info(), lambda event: None)
    ws = ClosingWS()
    client._ws = ws
    client._connected = True
    called = []
    monkeypatch.setattr(client, "_attempt_reconnect", lambda: called.append(True))

    client.force_reconnect("stale_level_one")

    assert ws.closed is True
    assert client._connected is False
    assert called == [True]
