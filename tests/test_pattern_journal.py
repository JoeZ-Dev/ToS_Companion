import json

from momentum_companion.recording.pattern_journal import PatternEventJournal
from momentum_companion.recording.provenance import build_recording_provenance
from momentum_companion.replay.catalog import RecordingCatalog


def observation(*, state="VALID", evidence=None):
    return {
        "id": "AEHL:ASCENDING_TRIANGLE:10",
        "symbol": "AEHL",
        "pattern_type": "ASCENDING_TRIANGLE",
        "state": state,
        "started_at": 10,
        "updated_at": 20,
        "evidence": evidence or {"touches": 3},
        "points": [{"time": 10, "price": 3.1, "role": "support"}],
        "lines": [],
    }


def test_journal_records_contract_and_detector_provenance(tmp_path):
    session = tmp_path / "2026-09-27_080000_session"
    session.mkdir()
    provenance = build_recording_provenance(
        git_revision="a" * 40,
        git_worktree_dirty=False,
        app_version="test",
    )
    journal = PatternEventJournal(session, provenance=provenance)

    assert journal.append_observations([observation()], observation_ts_ms=20_000) == 1
    journal.close()

    event = json.loads((session / "pattern_events.jsonl").read_text())
    assert event["kind"] == "pattern_event"
    assert event["session_id"] == session.name
    assert event["symbol"] == "AEHL"
    assert event["pattern_id"] == "AEHL:ASCENDING_TRIANGLE:10"
    assert event["pattern_start_ts_ms"] == 10_000
    assert event["observation_ts_ms"] == 20_000
    assert event["geometry"]["points"][0]["role"] == "support"
    assert event["detector"]["name"] == "ASCENDING_TRIANGLE"
    assert event["detector"]["config_fingerprint"].startswith("sha256:")
    assert event["source_mode"] == "live"
    assert event["event_id"].startswith("sha256:")


def test_journal_skips_unchanged_snapshots_but_records_transitions(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    journal = PatternEventJournal(
        session,
        provenance=build_recording_provenance(),
    )

    assert journal.append_observations([observation()], observation_ts_ms=20_000) == 1
    assert journal.append_observations([observation()], observation_ts_ms=30_000) == 0
    assert journal.append_observations([], observation_ts_ms=40_000) == 0
    assert journal.append_observations(
        [observation(state="BREAKOUT")], observation_ts_ms=50_000
    ) == 1
    journal.close()

    lines = (session / "pattern_events.jsonl").read_text().splitlines()
    assert [json.loads(line)["state"] for line in lines] == ["VALID", "BREAKOUT"]


def test_catalog_loads_pattern_journal_and_legacy_session_without_one(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps({"kind": "market_day_recording", "symbols": ["AEHL"]})
    )
    events = [
        {
            "kind": "pattern_event",
            "event_id": "later",
            "symbol": "AEHL",
            "observation_ts_ms": 20_000,
        },
        {
            "kind": "pattern_event",
            "event_id": "earlier",
            "symbol": "TOPS",
            "observation_ts_ms": 10_000,
        },
    ]
    (session / "pattern_events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n"
    )
    catalog = RecordingCatalog(tmp_path)

    assert [event["event_id"] for event in catalog.load_pattern_events("session")] == [
        "earlier",
        "later",
    ]
    assert catalog.load_pattern_events("session", symbol="aehl")[0]["event_id"] == "later"
    (session / "pattern_events.jsonl").unlink()
    assert catalog.load_pattern_events("session") == []
