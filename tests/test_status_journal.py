import json

from momentum_companion.recording.status_journal import SecurityStatusJournal
from momentum_companion.replay.catalog import RecordingCatalog


def status_payload(status, *, timestamp=1_700_000_000_000, **extra):
    fields = {"key": "AEHL", "32": status, **extra}
    return {
        "data": [
            {
                "service": "LEVELONE_EQUITIES",
                "timestamp": timestamp,
                "content": [fields],
            }
        ]
    }


def test_status_journal_records_only_explicit_transitions(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    journal = SecurityStatusJournal(session)

    assert journal.append_payload(
        status_payload("Normal"),
        active_symbols={"AEHL"},
        observed_at_utc="2026-09-27T13:00:00Z",
    ) == 1
    assert journal.append_payload(
        status_payload("Normal", timestamp=1_700_000_001_000),
        active_symbols={"AEHL"},
        observed_at_utc="2026-09-27T13:00:01Z",
    ) == 0
    assert journal.append_payload(
        {
            "service": "LEVELONE_EQUITIES",
            "timestamp": 1_700_000_002_000,
            "content": [{"key": "AEHL", "3": 3.12}],
        },
        active_symbols={"AEHL"},
        observed_at_utc="2026-09-27T13:00:02Z",
    ) == 0
    assert journal.append_payload(
        status_payload(
            "Halted",
            timestamp=1_700_000_003_000,
            statusReason="News pending",
            statusReasonCode="T1",
        ),
        active_symbols={"AEHL"},
        observed_at_utc="2026-09-27T13:00:03Z",
    ) == 1
    journal.close()

    events = [
        json.loads(line)
        for line in (session / "security_status_events.jsonl").read_text().splitlines()
    ]
    assert [event["provider_status"] for event in events] == ["Normal", "Halted"]
    halted = events[1]
    assert halted["provider_reason"] == "News pending"
    assert halted["provider_reason_code"] == "T1"
    assert halted["provider_ts_ms"] == 1_700_000_003_000
    assert halted["observed_at_utc"] == "2026-09-27T13:00:03Z"
    assert halted["provider_timestamp_source"] == "message.timestamp"
    assert halted["source_mode"] == "live"


def test_status_journal_ignores_unrecorded_symbol(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    journal = SecurityStatusJournal(session)

    assert journal.append_payload(
        status_payload("Halted"),
        active_symbols={"TOPS"},
        observed_at_utc="2026-09-27T13:00:00Z",
    ) == 0
    journal.close()
    assert not (session / "security_status_events.jsonl").exists()


def test_catalog_loads_status_events_and_legacy_session_without_them(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps({"kind": "market_day_recording", "symbols": ["AEHL"]})
    )
    events = [
        {
            "kind": "security_status_event",
            "event_id": "later",
            "symbol": "AEHL",
            "provider_ts_ms": 20,
        },
        {
            "kind": "security_status_event",
            "event_id": "earlier",
            "symbol": "TOPS",
            "provider_ts_ms": 10,
        },
    ]
    path = session / "security_status_events.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n")
    catalog = RecordingCatalog(tmp_path)

    assert [
        event["event_id"] for event in catalog.load_security_status_events("session")
    ] == ["earlier", "later"]
    assert catalog.load_security_status_events("session", symbol="aehl")[0][
        "event_id"
    ] == "later"
    path.unlink()
    assert catalog.load_security_status_events("session") == []
