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
