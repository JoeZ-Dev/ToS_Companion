import json
from pathlib import Path

from momentum_companion.replay.catalog import RecordingCatalog
from momentum_companion.replay.engine import ReplayEngine


def _write_session(root: Path) -> Path:
    session = root / "2026-09-23_070000_session"
    session.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "kind": "market_day_recording",
        "symbols": ["TOPS"],
        "services": ["LEVELONE_EQUITIES"],
        "started_at_et": "2026-09-23T07:00:00-04:00",
        "ended_at_et": "2026-09-23T15:00:00-04:00",
        "stop_reason": "3pm_cutoff",
        "counts": {"TOPS": {"LEVELONE_EQUITIES": 3}},
    }
    (session / "manifest.json").write_text(json.dumps(manifest))
    rows = [
        {
            "schema_version": 1,
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "TOPS",
            "stream_ts_ms": 1790161200000,
            "received_at": "2026-09-23T11:00:00Z",
            "raw": {"key": "TOPS", "1": 0.70, "2": 0.71, "3": 0.705, "8": 1000},
        },
        {
            "schema_version": 1,
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "TOPS",
            "stream_ts_ms": 1790161205000,
            "received_at": "2026-09-23T11:00:05Z",
            "raw": {"key": "TOPS", "3": 0.710, "8": 1200},
        },
        {
            "schema_version": 1,
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "TOPS",
            "stream_ts_ms": 1790161210000,
            "received_at": "2026-09-23T11:00:10Z",
            "raw": {"key": "TOPS", "3": 0.720, "8": 1500},
        },
    ]
    with (session / "TOPS.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return session


def test_catalog_lists_recorded_sessions_without_opening_live_services(tmp_path):
    session = _write_session(tmp_path)
    catalog = RecordingCatalog(tmp_path)

    sessions = catalog.list_sessions()

    assert sessions == [{
        "session_id": session.name,
        "started_at_et": "2026-09-23T07:00:00-04:00",
        "ended_at_et": "2026-09-23T15:00:00-04:00",
        "symbols": ["TOPS"],
        "counts": {"TOPS": {"LEVELONE_EQUITIES": 3}},
        "stop_reason": "3pm_cutoff",
    }]


def test_catalog_rejects_path_traversal(tmp_path):
    catalog = RecordingCatalog(tmp_path)

    try:
        catalog.load_events("../etc", "TOPS")
    except ValueError as exc:
        assert "session_id" in str(exc)
    else:
        raise AssertionError("path traversal must be rejected")


def test_replay_step_uses_recorded_deltas_to_build_same_ten_second_bar(tmp_path):
    session = _write_session(tmp_path)
    engine = ReplayEngine(recordings_root=tmp_path)

    loaded = engine.load(session.name, "TOPS")
    assert loaded["total_events"] == 3
    assert loaded["cursor"] == 0

    engine.step(3)
    state = engine.snapshot()

    assert state["replay"]["cursor"] == 3
    assert state["replay"]["status"] == "COMPLETE"
    assert state["session"]["symbols"]["TOPS"]["quote"]["last"] == 0.720
    assert state["session"]["symbols"]["TOPS"]["quote"]["bid"] == 0.70
    assert state["session"]["symbols"]["TOPS"]["bars_10s"][0]["open"] == 0.705
    assert state["session"]["symbols"]["TOPS"]["bars_10s"][0]["close"] == 0.710


def test_replay_seek_rebuilds_state_from_start_without_future_leakage(tmp_path):
    session = _write_session(tmp_path)
    engine = ReplayEngine(recordings_root=tmp_path)
    engine.load(session.name, "TOPS")
    engine.step(3)

    engine.seek(1)
    state = engine.snapshot()

    assert state["replay"]["cursor"] == 1
    assert state["replay"]["status"] == "PAUSED"
    assert state["session"]["symbols"]["TOPS"]["quote"]["last"] == 0.705
    assert state["session"]["symbols"]["TOPS"]["bars_10s"] == []


def test_replay_analysis_uses_replay_clock_not_wall_clock(tmp_path):
    session = tmp_path / "2026-09-23_070000_session"
    session.mkdir(parents=True)
    (session / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "kind": "market_day_recording",
        "symbols": ["TOPS"],
        "services": ["LEVELONE_EQUITIES"],
        "started_at_et": "2026-09-23T07:00:00-04:00",
        "ended_at_et": "2026-09-23T15:00:00-04:00",
        "counts": {"TOPS": {"LEVELONE_EQUITIES": 8}},
    }))
    base = 1790161200000
    with (session / "TOPS.jsonl").open("w", encoding="utf-8") as handle:
        for index in range(8):
            raw = {"key": "TOPS", "3": 0.70 + index * 0.01, "8": 1000 + index * 100}
            if index == 0:
                raw.update({"1": 0.69, "2": 0.71})
            handle.write(json.dumps({
                "schema_version": 1,
                "kind": "market_event",
                "service": "LEVELONE_EQUITIES",
                "symbol": "TOPS",
                "stream_ts_ms": base + index * 10_000,
                "received_at": "2026-09-23T11:00:00Z",
                "raw": raw,
            }) + "\n")

    engine = ReplayEngine(recordings_root=tmp_path)
    engine.load(session.name, "TOPS")
    engine.step(8)
    snapshot = engine.snapshot()["session"]["symbols"]["TOPS"]["ae_snapshot"]

    assert snapshot is not None
    assert snapshot["symbol"] == "TOPS"
    assert snapshot["as_of_ts_ms"] == base + 70_000


def test_replay_max_speed_runs_to_completion(tmp_path):
    session = _write_session(tmp_path)
    engine = ReplayEngine(recordings_root=tmp_path)
    engine.load(session.name, "TOPS")

    state = engine.play("MAX")
    assert state["status"] in {"PLAYING", "COMPLETE"}

    import time
    deadline = time.time() + 2
    while time.time() < deadline and engine.snapshot()["replay"]["status"] != "COMPLETE":
        time.sleep(0.01)

    final = engine.snapshot()["replay"]
    assert final["status"] == "COMPLETE"
    assert final["cursor"] == final["total_events"]


def test_replay_rejects_unsupported_speed(tmp_path):
    session = _write_session(tmp_path)
    engine = ReplayEngine(recordings_root=tmp_path)
    engine.load(session.name, "TOPS")

    try:
        engine.play(7)
    except ValueError as exc:
        assert "speed" in str(exc)
    else:
        raise AssertionError("unsupported replay speed must fail")


def test_replay_resolves_cursor_at_or_before_timestamp(tmp_path):
    session = _write_session(tmp_path)
    engine = ReplayEngine(recordings_root=tmp_path)
    engine.load(session.name, "TOPS")

    assert engine.cursor_for_timestamp(1790161200000) == 1
    assert engine.cursor_for_timestamp(1790161207500) == 2
    assert engine.cursor_for_timestamp(1790161199000) == 0
    assert engine.cursor_for_timestamp(1790169999999) == 3


def test_data_quality_only_summarizes_consumed_prefix_and_rebuilds_on_seek(tmp_path):
    session = _write_session(tmp_path)
    path = session / "TOPS.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["received_at"] = "2026-09-23T10:59:59Z"
    rows[1]["received_at"] = "not a timestamp"
    rows[2]["stream_ts_ms"] += 120000
    rows[2]["received_at"] = "2026-09-23T11:02:12Z"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    engine = ReplayEngine(recordings_root=tmp_path)
    initial = engine.load(session.name, "TOPS")
    quality = initial["data_quality"]
    assert quality["evidence_tier"] == "L1"
    assert quality["partial_context"] is True
    assert quality["timestamp_source"] == "stream_ts_ms"
    assert quality["receive_offset_ms"] == {"count": 0, "min": None, "max": None, "median": None}
    assert quality["significant_gap"] == {"threshold_ms": 60000, "count": 0, "largest_ms": 0, "cause": "unknown"}

    first = engine.step(1)["data_quality"]
    assert first["receive_offset_ms"] == {"count": 1, "min": -1000, "max": -1000, "median": -1000}
    assert first["significant_gap"]["count"] == 0
    final = engine.step(2)["data_quality"]
    assert final["receive_offset_ms"] == {"count": 2, "min": -1000, "max": 2000, "median": 500}
    assert final["significant_gap"]["count"] == 1
    assert final["significant_gap"]["largest_ms"] == 125000
    assert final["volume"] == {"capped_total": 0, "discarded_total": 0}

    assert engine.seek(1)["data_quality"] == first
    assert engine.seek(3)["data_quality"] == final


def test_replay_missing_receive_timestamp_is_ignored(tmp_path):
    session = _write_session(tmp_path)
    path = session / "TOPS.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0].pop("received_at")
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    engine = ReplayEngine(recordings_root=tmp_path)
    engine.load(session.name, "TOPS")
    assert engine.step(1)["data_quality"]["receive_offset_ms"]["count"] == 0


def test_replay_reports_volume_removed_by_cap_and_reset_without_changing_bar_volume(tmp_path):
    session = _write_session(tmp_path)
    base = 1790161200000
    volumes = [1000] + [1000 + second * 100 for second in range(1, 11)] + [502000, 500000]
    rows = [
        {
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "TOPS",
            "stream_ts_ms": base + index * 1000,
            "raw": {"key": "TOPS", "3": 0.7, "8": volume},
        }
        for index, volume in enumerate(volumes)
    ]
    rows[0]["raw"].update({"1": 0.69, "2": 0.71})
    (session / "TOPS.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

    engine = ReplayEngine(recordings_root=tmp_path)
    engine.load(session.name, "TOPS")
    before_cap = engine.step(11)["data_quality"]
    assert before_cap["volume"] == {"capped_total": 0, "discarded_total": 0}
    capped = engine.step()["data_quality"]
    assert capped["volume"] == {"capped_total": 250000, "discarded_total": 0}
    reset = engine.step()["data_quality"]
    assert reset["volume"] == {"capped_total": 250000, "discarded_total": 2000}
    assert engine.snapshot()["session"]["symbols"]["TOPS"]["bars_10s"][0]["volume"] == 900
    assert engine.seek(11)["data_quality"] == before_cap
