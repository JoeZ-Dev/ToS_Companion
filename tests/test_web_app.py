import time

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

    def auth_status(self):
        return {
            "authorized": True,
            "auth_owner": "companion_auth",
            "helper_url_configured": True,
        }

    def readiness(self):
        return {
            "ok": True,
            "auth_owner": "companion_auth",
            "companion_auth_authorized": True,
            "companion_auth_helper_configured": True,
            "llm_configured": False,
            "db_path": "/tmp/test.db",
            "recordings_root": "/tmp/recordings",
            "session_mode": "PRE",
        }

    def run_llm(self, symbol):
        result = {"stock_bias": "NO_EDGE", "setups": [], "summary": "test"}
        self.session.update_llm_output(symbol.upper(), result)
        return result

    def start_recording(self, symbols):
        state = {"active": True, "symbols": [s.upper() for s in symbols]}
        self.session.update_recorder_state(state)
        return state

    def stop_recording(self, reason="stopped"):
        state = {"active": False, "stop_reason": reason}
        self.session.update_recorder_state(state)
        return state

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
            while event["type"] != "quote":
                event = websocket.receive_json()

    assert event["type"] == "quote"
    assert event["symbol"] == "AEHL"
    assert event["payload"]["last"] == 3.20


def test_auth_status_never_returns_a_schwab_token():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        response = client.get("/api/auth/status")

    payload = response.json()
    assert payload["authorized"] is True
    assert payload["auth_owner"] == "companion_auth"
    assert "access_token" not in payload
    assert "refresh_token" not in payload


def test_manual_llm_endpoint_returns_immediately_and_updates_headless_state():
    runtime = FakeRuntime()
    runtime.session.add_symbol("AEHL", make_active=True)
    runtime.session.update_ae_snapshot(
        "AEHL",
        {"symbol": "AEHL", "status": "ok", "data_quality": "ok"},
    )

    with TestClient(create_app(runtime)) as client:
        response = client.post("/api/llm/run/AEHL")
        assert response.status_code == 202
        assert response.json()["accepted"] is True

        deadline = time.time() + 2
        while time.time() < deadline:
            output = runtime.session.snapshot()["symbols"]["AEHL"]["llm_output"]
            if output is not None:
                break
            time.sleep(0.01)

    assert runtime.session.snapshot()["symbols"]["AEHL"]["llm_output"]["summary"] == "test"


def test_browser_recording_controls_are_server_side():
    runtime = FakeRuntime()

    with TestClient(create_app(runtime)) as client:
        start = client.post("/api/recording/start", json={"symbols": ["aehl", "tops"]})
        stop = client.post("/api/recording/stop")

    assert start.status_code == 200
    assert start.json()["symbols"] == ["AEHL", "TOPS"]
    assert stop.status_code == 200
    assert stop.json()["stop_reason"] == "browser_stop"


def test_readiness_is_non_secret_and_reports_auth_owner():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        response = client.get("/api/readiness")

    payload = response.json()
    assert payload["ok"] is True
    assert payload["auth_owner"] == "companion_auth"
    assert payload["companion_auth_authorized"] is True
    assert "access_token" not in payload
    assert "refresh_token" not in payload


def test_browser_assets_are_not_cached():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        response = client.get("/app.js")

    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
