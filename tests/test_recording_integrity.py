import json

from momentum_companion.recording.integrity import (
    build_integrity_report,
    write_integrity_report,
)
from momentum_companion.recording.provenance import build_recording_provenance


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_integrity_report_summarizes_gaps_repairs_journals_and_provenance(tmp_path):
    session = tmp_path / "2026-09-27_080000_session"
    session.mkdir()
    manifest = {
        "schema_version": 2,
        "kind": "market_day_recording",
        "symbols": ["AEHL"],
        "started_at_et": "2026-09-27T08:00:00-04:00",
        "ended_at_et": "2026-09-27T09:00:00-04:00",
        "provenance": build_recording_provenance(
            git_revision="a" * 40,
            git_worktree_dirty=False,
            app_version="test",
        ),
        "derived_artifacts": {
            "pattern_events": {"path": "pattern_events.jsonl"},
            "security_status_events": {"path": "security_status_events.jsonl"},
        },
    }
    (session / "manifest.json").write_text(json.dumps(manifest))
    _write_jsonl(
        session / "AEHL.jsonl",
        [
            {
                "kind": "market_event",
                "service": "LEVELONE_EQUITIES",
                "symbol": "AEHL",
                "stream_ts_ms": 0,
                "raw": {"key": "AEHL"},
            },
            {
                "kind": "historical_candle",
                "symbol": "AEHL",
                "stream_ts_ms": 60_000,
                "candle": {},
            },
            {
                "kind": "historical_candle",
                "symbol": "AEHL",
                "stream_ts_ms": 120_000,
                "candle": {},
            },
            {
                "kind": "market_event",
                "service": "LEVELONE_EQUITIES",
                "symbol": "AEHL",
                "stream_ts_ms": 180_000,
                "raw": {"key": "AEHL"},
            },
            {
                "kind": "market_event",
                "service": "LEVELONE_EQUITIES",
                "symbol": "AEHL",
                "stream_ts_ms": 300_000,
                "raw": {"key": "AEHL"},
            },
        ],
    )
    _write_jsonl(
        session / "pattern_events.jsonl",
        [
            {
                "kind": "pattern_event",
                "event_id": "p1",
                "symbol": "AEHL",
                "pattern_type": "ASCENDING_TRIANGLE",
                "state": "VALID",
                "observation_ts_ms": 180_000,
            },
            {
                "kind": "pattern_event",
                "event_id": "p2",
                "symbol": "AEHL",
                "pattern_type": "ASCENDING_TRIANGLE",
                "state": "BREAKOUT",
                "observation_ts_ms": 300_000,
            },
        ],
    )
    _write_jsonl(
        session / "security_status_events.jsonl",
        [
            {
                "kind": "security_status_event",
                "event_id": "s1",
                "symbol": "AEHL",
                "provider_status": "Halted",
                "provider_ts_ms": 200_000,
            }
        ],
    )

    report = build_integrity_report(session)
    symbol = report["symbols"]["AEHL"]

    assert report["provenance"] == {"complete": True, "missing_fields": []}
    assert symbol["first_timestamp_ms"] == 0
    assert symbol["last_timestamp_ms"] == 300_000
    assert symbol["raw_event_count"] == 3
    assert symbol["repaired_historical_candle_count"] == 2
    assert symbol["gaps"]["detected_count"] == 2
    assert symbol["gaps"]["repaired_count"] == 1
    assert symbol["gaps"]["unresolved_count"] == 1
    assert symbol["gaps"]["maximum_duration_ms"] == 180_000
    assert symbol["pattern_events"]["by_detector"] == {"ASCENDING_TRIANGLE": 2}
    assert symbol["pattern_events"]["by_state"] == {"BREAKOUT": 1, "VALID": 1}
    assert symbol["status_events"]["halt_count"] == 1
    assert report["totals"]["unresolved_gaps"] == 1

    written = write_integrity_report(session)
    persisted = json.loads((session / "integrity_report.json").read_text())
    assert persisted["session_id"] == written["session_id"]


def test_integrity_report_marks_legacy_unknowns_and_missing_recording(tmp_path):
    session = tmp_path / "legacy"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps({"kind": "market_day_recording", "symbols": ["TOPS"]})
    )

    report = build_integrity_report(session)
    codes = {
        warning["code"]
        for warning in report["symbols"]["TOPS"]["replay_confidence_warnings"]
    }
    assert report["provenance"]["complete"] is False
    assert "recording_active" in {warning["code"] for warning in report["warnings"]}
    assert "application.git_revision" in report["provenance"]["missing_fields"]
    assert "recording_file_missing" in codes
    assert "pattern_journal_unavailable" in codes
    assert "status_history_unavailable" in codes
