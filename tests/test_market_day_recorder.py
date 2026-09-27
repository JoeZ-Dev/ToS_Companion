import json
from datetime import datetime
from pathlib import Path

from momentum_companion.recording.history import (
    load_recorded_minute_candles,
    merge_candles_prefer_primary,
)
from momentum_companion.recording.market_day import (
    ET,
    MarketDayRecorder,
    build_subscription_requests,
    normalize_symbols,
    reached_cutoff,
)
from momentum_companion.recording.provenance import (
    FROZEN_DETECTOR_REVISIONS,
    MANIFEST_SCHEMA_VERSION,
    application_git_state,
    build_recording_provenance,
    deterministic_fingerprint,
)


def test_normalize_symbols_supports_multiple_and_deduplicates():
    assert normalize_symbols([" aehL ", "TOPS", "aehl", ""]) == ["AEHL", "TOPS"]


def test_cutoff_is_3pm_eastern():
    assert reached_cutoff(datetime(2026, 9, 21, 14, 59, 59, tzinfo=ET)) is False
    assert reached_cutoff(datetime(2026, 9, 21, 15, 0, 0, tzinfo=ET)) is True


def test_subscription_requests_default_to_supported_level_one_only():
    info = {"schwabClientCustomerId": "c", "schwabClientCorrelId": "r"}
    requests = build_subscription_requests(info, ["AEHL", "TOPS"])
    assert [request["service"] for request in requests] == ["LEVELONE_EQUITIES"]
    assert requests[0]["parameters"]["keys"] == "AEHL,TOPS"


def test_timesales_requires_explicit_experimental_opt_in():
    info = {"schwabClientCustomerId": "c", "schwabClientCorrelId": "r"}
    requests = build_subscription_requests(
        info, ["AEHL", "TOPS"], include_timesales=True
    )
    assert [request["service"] for request in requests] == [
        "LEVELONE_EQUITIES",
        "TIMESALE_EQUITY",
    ]


def test_recorder_routes_each_stream_entry_to_its_symbol_file(tmp_path: Path):
    recorder = MarketDayRecorder(
        ["AEHL", "TOPS"],
        output_root=tmp_path,
        services={"LEVELONE_EQUITIES", "TIMESALE_EQUITY"},
    )
    payload = {
        "data": [
            {
                "service": "TIMESALE_EQUITY",
                "timestamp": 1234567890000,
                "content": [
                    {"key": "AEHL", "1": 1234567889000, "2": 3.21, "3": 100, "4": 77},
                    {"key": "TOPS", "1": 1234567889001, "2": 1.11, "3": 250, "4": 88},
                ],
            }
        ]
    }

    recorder.record_payload(payload, received_at="2026-09-21T13:00:00Z")
    recorder.close()

    aehl = (recorder.session_dir / "AEHL.jsonl").read_text()
    tops = (recorder.session_dir / "TOPS.jsonl").read_text()

    assert '"service":"TIMESALE_EQUITY"' in aehl
    assert '"symbol":"AEHL"' in aehl
    assert '"symbol":"TOPS"' not in aehl
    assert '"symbol":"TOPS"' in tops


def test_recorder_derives_explicit_security_status_history(tmp_path: Path):
    recorder = MarketDayRecorder(["AEHL"], output_root=tmp_path)
    recorder.record_payload(
        {
            "data": [
                {
                    "service": "LEVELONE_EQUITIES",
                    "timestamp": 1_700_000_000_000,
                    "content": [
                        {
                            "key": "AEHL",
                            "1": 3.10,
                            "2": 3.12,
                            "3": 3.11,
                            "8": 25_000,
                            "32": "Halted",
                        }
                    ],
                }
            ]
        },
        received_at="2026-09-27T13:00:00Z",
    )
    recorder.close()

    status_event = json.loads(
        (recorder.session_dir / "security_status_events.jsonl").read_text()
    )
    manifest = json.loads((recorder.session_dir / "manifest.json").read_text())
    assert status_event["provider_status"] == "Halted"
    assert manifest["derived_artifacts"]["security_status_events"] == {
        "path": "security_status_events.jsonl",
        "schema_version": 1,
        "event_count": 1,
    }
    assert recorder.state()["security_status_event_count"] == 1


def test_status_journal_failure_does_not_block_raw_recording(tmp_path: Path, monkeypatch):
    recorder = MarketDayRecorder(["AEHL"], output_root=tmp_path)

    def fail_status_write(*args, **kwargs):
        raise OSError("derived journal unavailable")

    monkeypatch.setattr(recorder._status_journal, "append_payload", fail_status_write)
    recorder.record_payload(
        {
            "service": "LEVELONE_EQUITIES",
            "timestamp": 1_700_000_000_000,
            "content": [
                {
                    "key": "AEHL",
                    "1": 3.10,
                    "2": 3.12,
                    "3": 3.11,
                    "8": 25_000,
                    "32": "Halted",
                }
            ],
        }
    )
    recorder.close()

    raw = json.loads((recorder.session_dir / "AEHL.jsonl").read_text())
    assert raw["raw"]["32"] == "Halted"


def test_non_recorded_services_are_ignored(tmp_path: Path):
    recorder = MarketDayRecorder(["AEHL"], output_root=tmp_path)
    recorder.record_payload(
        {"data": [{"service": "CHART_EQUITY", "content": [{"key": "AEHL", "2": 3.2}]}]},
        received_at="2026-09-21T13:00:00Z",
    )
    recorder.close()

    assert not (recorder.session_dir / "AEHL.jsonl").exists()


def test_default_manifest_declares_level_one_only(tmp_path: Path):
    recorder = MarketDayRecorder(["AEHL"], output_root=tmp_path)
    recorder.close()

    import json
    manifest = json.loads((recorder.session_dir / "manifest.json").read_text())
    assert manifest["services"] == ["LEVELONE_EQUITIES"]
    assert "TIMESALE_EQUITY" not in manifest["counts"]["AEHL"]
    assert (recorder.session_dir / "integrity_report.json").exists()
    assert (recorder.session_dir / "pattern_outcomes.json").exists()
    assert (recorder.session_dir / "pattern_overlaps.json").exists()


def test_recorder_journals_patterns_only_for_active_symbols(tmp_path: Path):
    recorder = MarketDayRecorder(["AEHL"], output_root=tmp_path)
    event = {
        "id": "AEHL:TEST_PATTERN:10",
        "symbol": "AEHL",
        "pattern_type": "TEST_PATTERN",
        "state": "FORMING",
        "started_at": 10,
        "evidence": {},
        "points": [],
        "lines": [],
    }

    assert recorder.record_pattern_observations(
        "AEHL", [event], observation_ts_ms=20_000
    ) == 1
    recorder.remove_symbol("AEHL")
    assert recorder.record_pattern_observations(
        "AEHL", [event], observation_ts_ms=30_000
    ) == 0
    recorder.close()

    manifest = json.loads((recorder.session_dir / "manifest.json").read_text())
    artifact = manifest["derived_artifacts"]["pattern_events"]
    assert artifact["path"] == "pattern_events.jsonl"
    assert artifact["schema_version"] == 1
    assert artifact["event_count"] == 1


def test_new_manifest_records_runtime_and_detector_provenance(tmp_path: Path):
    provenance = build_recording_provenance(
        git_revision="a" * 40,
        git_worktree_dirty=False,
        app_version="test-version",
    )
    recorder = MarketDayRecorder(
        ["AEHL"],
        output_root=tmp_path,
        provenance=provenance,
    )
    recorder.close()

    import json
    manifest = json.loads((recorder.session_dir / "manifest.json").read_text())
    recorded = manifest["provenance"]
    enabled = recorded["detectors"]["enabled"]

    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert recorded["application"] == {
        "git_revision": "a" * 40,
        "git_worktree_dirty": False,
        "version": "test-version",
    }
    assert [item["name"] for item in enabled] == [
        "ASCENDING_TRIANGLE",
        "MICRO_PULLBACK",
        "LOCAL_RESISTANCE_BREAKOUT",
        "TIGHT_CONSOLIDATION_BREAKOUT",
    ]
    micro = next(item for item in enabled if item["name"] == "MICRO_PULLBACK")
    assert micro["semantic_revision"] == FROZEN_DETECTOR_REVISIONS["MICRO_PULLBACK"]
    assert micro["config_fingerprint"] == deterministic_fingerprint(micro["config"])
    assert recorded["schemas"] == {
        "manifest": 2,
        "market_event": 1,
        "derived_journal": 1,
    }
    assert recorded["pattern_evaluation"]["bar_cadence_seconds"] == 10
    assert recorded["session"]["timezone"] == "America/New_York"


def test_deployed_git_revision_can_be_supplied_without_git_checkout(monkeypatch):
    monkeypatch.setenv("TOS_COMPANION_GIT_REVISION", "b" * 40)
    monkeypatch.setenv("TOS_COMPANION_GIT_WORKTREE_DIRTY", "false")

    assert application_git_state() == ("b" * 40, False)


def test_manifest_counts_match_jsonl_records(tmp_path: Path):
    import json

    recorder = MarketDayRecorder(["AEHL"], output_root=tmp_path)
    for idx in range(3):
        recorder.record_payload(
            {
                "data": [
                    {
                        "service": "LEVELONE_EQUITIES",
                        "timestamp": 1234567890000 + idx,
                        "content": [
                            {
                                "key": "AEHL",
                                "1": 3.10 + idx * 0.01,
                                "2": 3.11 + idx * 0.01,
                                "3": 3.105 + idx * 0.01,
                                "8": 1000 + idx * 100,
                            }
                        ],
                    }
                ]
            },
            received_at=f"2026-09-22T13:00:0{idx}Z",
        )
    recorder.close(stop_reason="browser_stop")

    manifest = json.loads((recorder.session_dir / "manifest.json").read_text())
    jsonl_lines = [
        line
        for line in (recorder.session_dir / "AEHL.jsonl").read_text().splitlines()
        if line.strip()
    ]

    assert manifest["stop_reason"] == "browser_stop"
    assert manifest["counts"]["AEHL"]["LEVELONE_EQUITIES"] == 3
    assert len(jsonl_lines) == 3
    assert all(json.loads(line)["schema_version"] == 1 for line in jsonl_lines)


def test_recorded_l1_can_reconstruct_minute_candles(tmp_path: Path):
    started = datetime(2026, 9, 22, 4, 0, 0, tzinfo=ET)
    start_ms = int(started.timestamp() * 1000)
    recorder = MarketDayRecorder(
        ["IMCC"],
        output_root=tmp_path,
        started_at=started,
    )

    recorder.record_payload(
        {
            "data": [
                {
                    "service": "LEVELONE_EQUITIES",
                    "timestamp": start_ms + 5_000,
                    "content": [{"key": "IMCC", "3": 5.00, "8": 1000}],
                },
                {
                    "service": "LEVELONE_EQUITIES",
                    "timestamp": start_ms + 25_000,
                    "content": [{"key": "IMCC", "3": 5.20, "8": 1100}],
                },
                {
                    "service": "LEVELONE_EQUITIES",
                    "timestamp": start_ms + 65_000,
                    "content": [{"key": "IMCC", "8": 1200}],
                },
            ]
        },
        received_at="2026-09-22T08:01:05Z",
    )
    recorder.close()

    candles = load_recorded_minute_candles(
        "IMCC",
        start_ms,
        start_ms + 120_000,
        root=tmp_path,
    )

    assert len(candles) == 2
    assert candles[0]["datetime"] == start_ms
    assert candles[0]["open"] == 5.00
    assert candles[0]["high"] == 5.20
    assert candles[0]["low"] == 5.00
    assert candles[0]["close"] == 5.20
    assert candles[0]["volume"] == 100.0
    assert candles[1]["open"] == 5.20
    assert candles[1]["close"] == 5.20
    assert candles[1]["volume"] == 100.0


def test_schwab_candles_win_over_recorder_on_timestamp_collision():
    fallback = [
        {
            "datetime": 60_000,
            "open": 5.0,
            "high": 5.1,
            "low": 4.9,
            "close": 5.0,
            "volume": 100,
        },
        {
            "datetime": 120_000,
            "open": 5.1,
            "high": 5.2,
            "low": 5.0,
            "close": 5.15,
            "volume": 200,
        },
    ]
    primary = [
        {
            "datetime": 60_000,
            "open": 6.0,
            "high": 6.1,
            "low": 5.9,
            "close": 6.0,
            "volume": 300,
        }
    ]

    merged = merge_candles_prefer_primary(primary, fallback)

    assert [c["datetime"] for c in merged] == [60_000, 120_000]
    assert merged[0]["close"] == 6.0
    assert merged[1]["close"] == 5.15


def test_recorder_can_start_empty_then_add_remove_and_resume_symbol(tmp_path: Path):
    import json

    recorder = MarketDayRecorder([], output_root=tmp_path)
    assert recorder.active_symbols() == []

    assert recorder.add_symbol(" aehl ") is True
    assert recorder.add_symbol("AEHL") is False
    recorder.record_payload(
        {"data": [{"service": "LEVELONE_EQUITIES", "timestamp": 1, "content": [{"key": "AEHL", "3": 3.2, "8": 100}]}]},
        received_at="2026-09-23T13:00:00Z",
    )
    assert recorder.remove_symbol("AEHL") is True
    recorder.record_payload(
        {"data": [{"service": "LEVELONE_EQUITIES", "timestamp": 2, "content": [{"key": "AEHL", "3": 3.3, "8": 110}]}]},
        received_at="2026-09-23T13:01:00Z",
    )
    assert recorder.add_symbol("AEHL") is True
    recorder.record_payload(
        {"data": [{"service": "LEVELONE_EQUITIES", "timestamp": 3, "content": [{"key": "AEHL", "3": 3.4, "8": 120}]}]},
        received_at="2026-09-23T13:02:00Z",
    )
    recorder.close()

    lines = (recorder.session_dir / "AEHL.jsonl").read_text().splitlines()
    manifest = json.loads((recorder.session_dir / "manifest.json").read_text())
    assert len(lines) == 2
    assert manifest["counts"]["AEHL"]["LEVELONE_EQUITIES"] == 2
    assert len(manifest["symbol_lifecycle"]["AEHL"]["periods"]) == 2
    assert manifest["active_symbols"] == []


def test_pre7_seed_is_persisted_in_state_and_manifest(tmp_path: Path):
    import json

    recorder = MarketDayRecorder(["GCTK"], output_root=tmp_path)
    seed = recorder.set_pre7_seed("gctk", vwap=4.4233, volume=10570235)

    assert seed == {"vwap": 4.4233, "volume": 10570235.0}
    assert recorder.state()["pre7_seeds"]["GCTK"] == seed

    manifest = json.loads((recorder.session_dir / "manifest.json").read_text())
    assert manifest["pre7_seeds"]["GCTK"] == seed
