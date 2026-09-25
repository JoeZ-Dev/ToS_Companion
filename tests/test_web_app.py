import time
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient

from momentum_companion.session import CompanionSession
from momentum_companion.web import create_app


def test_chart_vwap_uses_backend_series_after_display_window_is_trimmed():
    script = Path(__file__).resolve().parents[1] / "src/momentum_companion/web/static/app.js"
    source = script.read_text()
    function = source[source.index("  function vwapPoints("):source.index("  function setStructuralLines(")]
    js = function + "\nconsole.log(JSON.stringify(vwapPoints({vwap_points:[{time:10,value:42.25}],history_bars:[{time:10,close:99,volume:100}],bars_10s:[]})));"
    result = subprocess.run(["node", "-e", js], text=True, capture_output=True, check=True)
    assert result.stdout.strip() == '[{"time":10,"value":42.25}]'


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
        normalized = [s.upper() for s in symbols]
        state = {"active": True, "symbols": normalized, "active_symbols": normalized}
        self.session.update_recorder_state(state)
        return state

    def add_recording_symbol(self, symbol, *, pre7_vwap=None, pre7_volume=None):
        state = dict(self.session.snapshot()["recorder_state"])
        symbols = list(state.get("symbols") or [])
        active_symbols = list(state.get("active_symbols") or symbols)
        normalized = symbol.upper()
        if normalized not in symbols:
            symbols.append(normalized)
        if normalized not in active_symbols:
            active_symbols.append(normalized)
        state.update({"active": True, "symbols": symbols, "active_symbols": active_symbols})
        if pre7_vwap is not None and pre7_volume is not None:
            seeds = dict(state.get("pre7_seeds") or {})
            seeds[normalized] = {"vwap": pre7_vwap, "volume": pre7_volume}
            state["pre7_seeds"] = seeds
        self.session.update_recorder_state(state)
        return state

    def apply_recording_pre7_seed(self, symbol, *, pre7_vwap, pre7_volume):
        return self.add_recording_symbol(
            symbol,
            pre7_vwap=pre7_vwap,
            pre7_volume=pre7_volume,
        )

    def remove_recording_symbol(self, symbol):
        state = dict(self.session.snapshot()["recorder_state"])
        normalized = symbol.upper()
        state["active_symbols"] = [s for s in state.get("active_symbols") or [] if s != normalized]
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


def test_browser_recording_symbols_can_be_added_and_removed_without_restart():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        start = client.post("/api/recording/start", json={"symbols": []})
        added = client.post("/api/recording/symbol", json={"symbol": "aehl"})
        removed = client.delete("/api/recording/symbol/AEHL")

    assert start.status_code == 200
    assert added.json()["active_symbols"] == ["AEHL"]
    assert removed.json()["active_symbols"] == []
    assert removed.json()["symbols"] == ["AEHL"]


def test_browser_surfaces_quote_freshness_indicator():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        index = client.get("/").text
        app_js = client.get("/app.js").text

    assert 'id="quote-freshness"' in index
    assert "_client_received_at_ms" in app_js
    assert "received_at_ms" in app_js
    assert "DELAYED" in app_js
    assert "STALE" in app_js
    assert "NO DATA" in app_js
    assert "ageMs < 1000" in app_js
    assert "ageMs < 3000" in app_js


class FakeReplayEngine:
    def __init__(self):
        self.calls = []
        self.value = {
            "replay": {
                "status": "PAUSED",
                "session_id": "2026-09-23_070000_session",
                "symbol": "TOPS",
                "cursor": 0,
                "total_events": 100,
                "current_ts_ms": 1790161200000,
                "progress": 0.0,
                "speed": 1,
            },
            "session": CompanionSession().snapshot(),
        }

    class Catalog:
        def list_sessions(self):
            return [{
                "session_id": "2026-09-23_070000_session",
                "started_at_et": "2026-09-23T07:00:00-04:00",
                "ended_at_et": "2026-09-23T15:00:00-04:00",
                "symbols": ["TOPS"],
                "counts": {"TOPS": {"LEVELONE_EQUITIES": 100}},
                "stop_reason": "3pm_cutoff",
            }]

    catalog = Catalog()

    def snapshot(self):
        return self.value

    def load(self, session_id, symbol):
        self.calls.append(("load", session_id, symbol))
        return self.value["replay"]

    def play(self, speed):
        self.calls.append(("play", speed))
        self.value["replay"]["status"] = "PLAYING"
        return self.value["replay"]

    def pause(self):
        self.calls.append(("pause",))
        self.value["replay"]["status"] = "PAUSED"
        return self.value["replay"]

    def step(self, count=1):
        self.calls.append(("step", count))
        return self.value["replay"]

    def seek(self, cursor):
        self.calls.append(("seek", cursor))
        return self.value["replay"]


def test_replay_api_is_separate_from_live_runtime():
    runtime = FakeRuntime()
    replay = FakeReplayEngine()

    with TestClient(create_app(runtime, replay_engine=replay)) as client:
        sessions = client.get("/api/replay/sessions")
        loaded = client.post(
            "/api/replay/load",
            json={"session_id": "2026-09-23_070000_session", "symbol": "TOPS"},
        )
        played = client.post("/api/replay/play", json={"speed": "MAX"})
        paused = client.post("/api/replay/pause")
        stepped = client.post("/api/replay/step", json={"count": 1})
        sought = client.post("/api/replay/seek", json={"cursor": 50})

    assert sessions.status_code == 200
    assert sessions.json()[0]["symbols"] == ["TOPS"]
    assert loaded.status_code == 200
    assert played.status_code == 200
    assert paused.status_code == 200
    assert stepped.status_code == 200
    assert sought.status_code == 200
    assert replay.calls == [
        ("load", "2026-09-23_070000_session", "TOPS"),
        ("play", "MAX"),
        ("pause",),
        ("step", 1),
        ("seek", 50),
    ]


def test_browser_exposes_replay_workspace():
    runtime = FakeRuntime()
    replay = FakeReplayEngine()

    with TestClient(create_app(runtime, replay_engine=replay)) as client:
        index = client.get("/").text
        app_js = client.get("/app.js").text

    assert 'data-tab="replay"' in index
    assert 'id="replay-session"' in index
    assert 'id="replay-symbol"' in index
    assert 'id="replay-progress"' in index
    assert "/api/replay/sessions" in app_js
    assert "/api/replay/play" in app_js
    assert "/api/replay/seek" in app_js


def test_stateless_replay_inspection_does_not_mutate_shared_replay(tmp_path, monkeypatch):
    from momentum_companion.replay.engine import ReplayEngine

    session = tmp_path / "2026-09-23_070000_session"
    session.mkdir(parents=True)
    (session / "manifest.json").write_text('{"kind":"market_day_recording","symbols":["TOPS"],"services":["LEVELONE_EQUITIES"],"counts":{"TOPS":{"LEVELONE_EQUITIES":2}}}')
    rows = [
        {"kind":"market_event","service":"LEVELONE_EQUITIES","symbol":"TOPS","stream_ts_ms":1000,"raw":{"key":"TOPS","1":1.0,"2":1.1,"3":1.05,"8":100}},
        {"kind":"market_event","service":"LEVELONE_EQUITIES","symbol":"TOPS","stream_ts_ms":2000,"raw":{"key":"TOPS","3":1.06,"8":120}},
    ]
    with (session / "TOPS.jsonl").open("w") as handle:
        for row in rows:
            handle.write(__import__("json").dumps(row) + "\n")

    runtime = FakeRuntime()
    shared = ReplayEngine(recordings_root=tmp_path)

    with TestClient(create_app(runtime, replay_engine=shared)) as client:
        response = client.post(
            "/api/replay/inspect",
            json={"session_id": session.name, "symbol": "TOPS", "cursor": 2},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["replay"]["cursor"] == 2
    assert payload["replay"]["data_quality"]["evidence_tier"] == "L1"
    assert payload["replay"]["data_quality"]["volume"] == {"capped_total": 0.0, "discarded_total": 0.0}
    assert payload["session"]["symbols"]["TOPS"]["quote"]["last"] == 1.06
    assert shared.snapshot()["replay"]["status"] == "EMPTY"


def test_recording_api_accepts_and_surfaces_pre7_seed():
    runtime = FakeRuntime()

    with TestClient(create_app(runtime)) as client:
        client.post("/api/recording/start", json={"symbols": []})
        response = client.post(
            "/api/recording/symbol",
            json={
                "symbol": "gctk",
                "pre7_vwap": 4.4233,
                "pre7_volume": 10570235,
            },
        )

    assert response.status_code == 200
    assert response.json()["pre7_seeds"]["GCTK"] == {
        "vwap": 4.4233,
        "volume": 10570235.0,
    }


def test_recording_page_exposes_pre7_inputs():
    runtime = FakeRuntime()

    with TestClient(create_app(runtime)) as client:
        index = client.get("/").text
        app_js = client.get("/app.js").text

    assert 'id="recorder-pre7-vwap"' in index
    assert 'id="recorder-pre7-volume"' in index
    assert "pre7_vwap" in app_js
    assert "PRE7 not set" in app_js


def test_browser_surfaces_momentum_context_fields():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        index = client.get("/").text
        app_js = client.get("/app.js").text

    assert 'id="security-status"' in index
    assert 'id="htb-status"' in index
    assert 'id="relative-strength"' in index
    assert "market_context" in app_js
    assert "shares_outstanding" in app_js
    assert "short_interest_to_float" in app_js
