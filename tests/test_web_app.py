import time
from pathlib import Path

from fastapi.testclient import TestClient

from momentum_companion.session import CompanionSession
from momentum_companion.web import create_app


class FakeRuntime:
    def __init__(self):
        self.session = CompanionSession()
        self.started = False
        self.stopped = False
        self.auth_workflow = {
            "authorized": True,
            "auth_owner": "companion_auth",
            "helper_url_configured": True,
            "status": "connected",
            "resume_recording_required": False,
        }

    def start(self):
        self.started = True
        self.session.update_connection_state("READY")

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return self.session.snapshot()

    def auth_status(self):
        return dict(self.auth_workflow)

    def begin_schwab_reauthorization(self):
        self.auth_workflow.update({"authorized": False, "status": "waiting"})
        return {
            **self.auth_workflow,
            "authorization_url": "https://api.schwabapi.com/v1/oauth/authorize?state=opaque",
        }

    def poll_schwab_reauthorization(self):
        return dict(self.auth_workflow)

    def resume_recording_after_authorization(self):
        self.auth_workflow["resume_recording_required"] = False
        return self.start_recording([])

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

    def add_recording_symbol(self, symbol):
        state = dict(self.session.snapshot()["recorder_state"])
        symbols = list(state.get("symbols") or [])
        active_symbols = list(state.get("active_symbols") or symbols)
        normalized = symbol.upper()
        if normalized not in symbols:
            symbols.append(normalized)
        if normalized not in active_symbols:
            active_symbols.append(normalized)
        state.update({"active": True, "symbols": symbols, "active_symbols": active_symbols})
        self.session.update_recorder_state(state)
        return state

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


def test_reauthorization_is_denied_outside_trusted_admin_boundary():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime, admin_authorizer=lambda assertion: False)) as client:
        response = client.post("/api/auth/reauthorize")

    assert response.status_code == 403
    assert runtime.auth_workflow["status"] == "connected"


def test_reauthorization_returns_only_official_url_and_redacted_state():
    runtime = FakeRuntime()
    authorize = lambda assertion: assertion == "signed-admin-assertion"
    with TestClient(create_app(runtime, admin_authorizer=authorize)) as client:
        response = client.post(
            "/api/auth/reauthorize",
            headers={"Cf-Access-Jwt-Assertion": "signed-admin-assertion"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "waiting"
    assert payload["authorization_url"].startswith(
        "https://api.schwabapi.com/v1/oauth/authorize"
    )
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text
    assert "client_secret" not in response.text
    assert "authorization_code" not in response.text


def test_reauthorization_status_and_resume_require_admin_boundary():
    runtime = FakeRuntime()
    runtime.auth_workflow["resume_recording_required"] = True
    authorize = lambda assertion: assertion == "admin"
    with TestClient(create_app(runtime, admin_authorizer=authorize)) as client:
        assert client.get("/api/auth/reauthorize/status").status_code == 403
        assert client.post("/api/auth/resume-recording").status_code == 403
        status = client.get(
            "/api/auth/reauthorize/status",
            headers={"Cf-Access-Jwt-Assertion": "admin"},
        )
        resumed = client.post(
            "/api/auth/resume-recording",
            headers={"Cf-Access-Jwt-Assertion": "admin"},
        )
    assert status.status_code == 200
    assert resumed.status_code == 200
    assert resumed.json()["active"] is True


def test_browser_has_persistent_reauthorization_states_and_no_credential_inputs():
    static_dir = Path(__file__).resolve().parents[1] / "src/momentum_companion/web/static"
    index = (static_dir / "index.html").read_text()
    app_js = (static_dir / "app.js").read_text()
    assert "Schwab authorization required" in index
    assert 'id="schwab-reconnect"' in index
    assert "Reconnect Schwab" in index
    for label in (
        "Authorization required",
        "Waiting for Schwab",
        "Verifying authorization",
        "Authorized and reconnecting",
        "Connected",
        "Authorization failed",
    ):
        assert label.lower() in (index + app_js).lower()
    assert 'type="password"' not in index
    assert "schwab_username" not in (index + app_js).lower()
    assert "schwab_password" not in (index + app_js).lower()


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
    assert payload["session"]["symbols"]["TOPS"]["quote"]["last"] == 1.06
    assert shared.snapshot()["replay"]["status"] == "EMPTY"



def test_wamo_review_recordings_compatibility_endpoint(tmp_path):
    from momentum_companion.replay.engine import ReplayEngine

    session = tmp_path / "2026-10-09_073202_session"
    session.mkdir(parents=True)
    (session / "manifest.json").write_text(
        '{"kind":"market_day_recording","symbols":["OFAL"],'
        '"services":["LEVELONE_EQUITIES"],'
        '"started_at_et":"2026-10-09T07:32:02-04:00",'
        '"ended_at_et":"2026-10-09T15:00:00-04:00",'
        '"stop_reason":"3pm_cutoff",'
        '"counts":{"OFAL":{"LEVELONE_EQUITIES":2}}}'
    )
    (session / "OFAL.jsonl").write_text("")

    runtime = FakeRuntime()
    shared = ReplayEngine(recordings_root=tmp_path)
    with TestClient(create_app(runtime, replay_engine=shared)) as client:
        response = client.get("/api/review/recordings")

    assert response.status_code == 200
    assert response.json()[0]["session_id"] == session.name
    assert response.json()[0]["symbols"] == ["OFAL"]


def test_wamo_review_window_is_future_safe_and_returns_10s_bars(tmp_path):
    import json
    from momentum_companion.replay.engine import ReplayEngine

    session = tmp_path / "2026-10-09_073202_session"
    session.mkdir(parents=True)
    (session / "manifest.json").write_text(
        '{"kind":"market_day_recording","symbols":["OFAL"],'
        '"services":["LEVELONE_EQUITIES"],'
        '"counts":{"OFAL":{"LEVELONE_EQUITIES":4}}}'
    )
    rows = [
        {"kind":"market_event","service":"LEVELONE_EQUITIES","symbol":"OFAL","stream_ts_ms":1000,"raw":{"key":"OFAL","1":0.49,"2":0.51,"3":0.50,"8":100}},
        {"kind":"market_event","service":"LEVELONE_EQUITIES","symbol":"OFAL","stream_ts_ms":11000,"raw":{"key":"OFAL","3":0.52,"8":120}},
        {"kind":"market_event","service":"LEVELONE_EQUITIES","symbol":"OFAL","stream_ts_ms":21000,"raw":{"key":"OFAL","3":0.54,"8":150}},
        {"kind":"market_event","service":"LEVELONE_EQUITIES","symbol":"OFAL","stream_ts_ms":31000,"raw":{"key":"OFAL","3":0.53,"8":180}},
    ]
    with (session / "OFAL.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    runtime = FakeRuntime()
    shared = ReplayEngine(recordings_root=tmp_path)
    with TestClient(create_app(runtime, replay_engine=shared)) as client:
        response = client.post(
            "/api/review/window",
            json={
                "session_id": session.name,
                "symbol": "OFAL",
                "start_ms": 1000,
                "end_ms": 31000,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["window"]["future_data_included"] is False
    assert payload["symbol"] == "OFAL"
    assert payload["replay"]["current_ts_ms"] == 31000
    assert payload["bars_10s"]
    assert payload["data_quality"]["evidence_tier"] == "L1"


def test_wamo_full_session_compatibility_retains_more_than_default_bar_cap(tmp_path):
    import json
    from momentum_companion.replay.engine import ReplayEngine

    session = tmp_path / "2026-10-09_073202_session"
    session.mkdir(parents=True)
    rows = []
    for index in range(620):
        rows.append({
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "OFAL",
            "stream_ts_ms": index * 10_000 + 1000,
            "raw": {"key": "OFAL", "1": 0.49, "2": 0.51, "3": 0.50 + index / 100000, "8": 100 + index},
        })
    (session / "manifest.json").write_text(
        json.dumps({
            "kind": "market_day_recording",
            "symbols": ["OFAL"],
            "services": ["LEVELONE_EQUITIES"],
            "counts": {"OFAL": {"LEVELONE_EQUITIES": len(rows)}},
        })
    )
    with (session / "OFAL.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    runtime = FakeRuntime()
    shared = ReplayEngine(recordings_root=tmp_path)
    with TestClient(create_app(runtime, replay_engine=shared)) as client:
        response = client.get(f"/api/review/session/{session.name}/OFAL")

    assert response.status_code == 200
    payload = response.json()
    assert payload["window"]["full_session"] is True
    assert len(payload["bars_10s"]) > 600
