from fastapi.testclient import TestClient

from momentum_companion.session import CompanionSession
from momentum_companion.web import create_app


class FakeRuntime:
    def __init__(self):
        self.session = CompanionSession()
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        self.session.update_connection_state("READY")

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return self.session.snapshot()

    def select_symbol(self, symbol):
        normalized = self.session.add_symbol(symbol, make_active=True)
        self.session.set_history(
            normalized,
            [
                {
                    "time": 1_700_000_000,
                    "open": 3.0,
                    "high": 3.2,
                    "low": 2.9,
                    "close": 3.1,
                    "volume": 1000,
                }
            ],
        )
        return self.session.snapshot()


def test_health_declares_companion_auth_as_auth_owner():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["auth_owner"] == "companion_auth"
    assert runtime.started is True
    assert runtime.stopped is True


def test_symbol_selection_updates_server_state():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        response = client.post("/api/symbol/aehl")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_symbol"] == "AEHL"
    assert payload["symbols"]["AEHL"]["history_bars"][0]["close"] == 3.1


def test_websocket_receives_initial_snapshot_and_live_events():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        with client.websocket_connect("/ws") as websocket:
            initial = websocket.receive_json()
            assert initial["type"] == "snapshot"

            runtime.session.ingest_quote(
                {
                    "ts_ms": 1_700_000_000_000,
                    "symbol": "AEHL",
                    "bid": 3.19,
                    "ask": 3.21,
                    "last": 3.20,
                    "bid_size": 100,
                    "ask_size": 100,
                    "last_size": 50,
                    "volume": 12345,
                    "source_ts_type": "TRADE_TS",
                    "raw_source": "SCHWAB_STREAM",
                }
            )
            event = websocket.receive_json()

    assert event["type"] == "symbol_added" or event["type"] == "active_symbol"
    # Drain ordering is intentionally event-based; quote follows symbol creation.
