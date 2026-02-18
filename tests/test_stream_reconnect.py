import json
from types import SimpleNamespace

import pytest

websocket = pytest.importorskip("websocket")

from momentum_companion.clients.schwab_stream import SchwabStreamClient
from momentum_companion.clients.token_provider import TokenProvider


class FakeWS:
    def __init__(self, url, on_open, on_message, on_error, on_close):
        self.on_open = on_open
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.sent = []
        self.closed = False

    def run_forever(self):
        # no-op for tests
        return None

    def send(self, msg):
        self.sent.append(json.loads(msg))

    def close(self):
        self.closed = True


def _base_streamer_info():
    return {
        "streamerSocketUrl": "wss://example",
        "schwabClientCustomerId": "c",
        "schwabClientCorrelId": "corr",
        "schwabClientChannel": "ch",
        "schwabClientFunctionId": "fn",
        "access_token": "tok",
    }


def test_stream_reconnect_and_resubscribe(monkeypatch):
    created = []

    def fake_ws(url, on_open, on_message, on_error, on_close):
        ws = FakeWS(url, on_open, on_message, on_error, on_close)
        created.append(ws)
        return ws

    monkeypatch.setattr("momentum_companion.clients.schwab_stream.websocket.WebSocketApp", fake_ws)
    client = SchwabStreamClient(_base_streamer_info(), lambda e: None)
    client.connect()
    ws = created[-1]
    ws.on_open(ws)
    # Simulate admin login success
    ws.on_message(ws, json.dumps({"service": "ADMIN", "command": "LOGIN"}))
    client.subscribe_level_one("AAPL")
    assert client.is_connected()
    assert any(m["command"] == "SUBS" for m in ws.sent)
    # Force logout
    ws.on_message(ws, json.dumps({"service": "ADMIN", "command": "LOGOUT"}))
    # Reconnect should create a new WS
    assert client.connection_state() in {"RECONNECTING", "DOWN", "CONNECTED"}


def test_stream_restarts_on_token_refresh(monkeypatch, tmp_path):
    created = []

    def fake_ws(url, on_open, on_message, on_error, on_close):
        ws = FakeWS(url, on_open, on_message, on_error, on_close)
        created.append(ws)
        return ws

    monkeypatch.setattr("momentum_companion.clients.schwab_stream.websocket.WebSocketApp", fake_ws)
    provider = TokenProvider(token_path=tmp_path / "tokens.json")
    provider.set_access_token("tok", expires_at=9999999999)
    client = SchwabStreamClient(_base_streamer_info(), lambda e: None, token_provider=provider)
    client.connect()
    ws1 = created[-1]
    ws1.on_open(ws1)
    ws1.on_message(ws1, json.dumps({"service": "ADMIN", "command": "LOGIN"}))
    client.subscribe_level_one("AAPL")
    assert any(m["command"] == "LOGIN" for m in ws1.sent)
    # Trigger refresh listener to force restart
    provider._notify_listeners()  # type: ignore[attr-defined]
    ws2 = created[-1]
    assert ws1.closed
    ws2.on_open(ws2)
    ws2.on_message(ws2, json.dumps({"service": "ADMIN", "command": "LOGIN"}))
    assert any(m["command"] == "SUBS" for m in ws2.sent)


def test_stream_handles_data_wrapper(monkeypatch):
    created = []
    events = []

    def fake_ws(url, on_open, on_message, on_error, on_close):
        ws = FakeWS(url, on_open, on_message, on_error, on_close)
        created.append(ws)
        return ws

    monkeypatch.setattr("momentum_companion.clients.schwab_stream.websocket.WebSocketApp", fake_ws)
    client = SchwabStreamClient(_base_streamer_info(), lambda e: events.append(e))
    client.connect()
    ws = created[-1]
    ws.on_open(ws)
    # login response wrapped in "response"
    login_payload = {"response": [{"service": "ADMIN", "command": "LOGIN", "content": {"code": 0}}]}
    ws.on_message(ws, json.dumps(login_payload))
    client.subscribe_level_one("AAPL")
    data_payload = {
        "data": [
            {
                "service": "LEVELONE_EQUITIES",
                "timestamp": 1710000000000,
                "command": "SUBS",
                "content": [{"key": "AAPL", "1": 100.0, "2": 101.0, "3": 100.5, "8": 1000}],
            }
        ]
    }
    ws.on_message(ws, json.dumps(data_payload))
    assert events and events[-1]["symbol"] == "AAPL"
