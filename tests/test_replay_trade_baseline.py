import json

from momentum_companion.evaluation.replay_trade_baseline import (
    CONTEXT_COMPLETENESS,
    SOURCE_MODE,
    STATUS_EVIDENCE,
    VIEWS,
    PatternJournalReplayEngine,
    _exclude_candidate_triggers,
    _group_summary,
    build_replay_trade_baseline,
)
from momentum_companion.recording.provenance import build_recording_provenance


def _write_session(root, session_id="2026-09-23_test"):
    session = root / session_id
    session.mkdir(parents=True)
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "kind": "market_day_recording",
                "schema_version": 1,
                "services": ["LEVELONE_EQUITIES"],
                "symbols": ["TEST"],
                "counts": {"TEST": {"LEVELONE_EQUITIES": 12}},
                "started_at_et": "2026-09-23T09:30:00-04:00",
                "ended_at_et": "2026-09-23T09:32:00-04:00",
            }
        ),
        encoding="utf-8",
    )
    base = 1_790_168_400_000
    prices = [10.0, 10.0, 10.01, 10.0, 10.01, 10.0, 10.0, 10.5, 10.55, 10.4, 10.3, 10.2]
    rows = []
    for index, price in enumerate(prices):
        rows.append(
            {
                "kind": "market_event",
                "service": "LEVELONE_EQUITIES",
                "symbol": "TEST",
                "stream_ts_ms": base + index * 10_000,
                "raw": {
                    "key": "TEST",
                    "1": price - 0.01,
                    "2": price + 0.01,
                    "3": price,
                    "8": 1_000 + index * 100,
                },
            }
        )
    (session / "TEST.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    (session / "TEST_history.json").write_text(
        json.dumps(
            {
                "kind": "historical_backfill",
                "symbol": "TEST",
                "candles": [
                    {
                        "datetime": base - 60_000,
                        "open": 1.0,
                        "high": 99.0,
                        "low": 1.0,
                        "close": 99.0,
                        "volume": 999_999,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return session


def _provenance():
    return build_recording_provenance(
        git_revision="a" * 40,
        git_worktree_dirty=False,
        app_version="test",
    )


def test_journal_replay_is_deterministic_causal_and_does_not_seed_history(tmp_path):
    session = _write_session(tmp_path)

    first = PatternJournalReplayEngine(
        recordings_root=tmp_path, provenance=_provenance()
    )
    loaded = first.load(session.name, "TEST")
    first.step(loaded["total_events"])
    full_events = first.generated_pattern_events

    second = PatternJournalReplayEngine(
        recordings_root=tmp_path, provenance=_provenance()
    )
    loaded_again = second.load(session.name, "TEST")
    second.step(loaded_again["total_events"])

    prefix = PatternJournalReplayEngine(
        recordings_root=tmp_path, provenance=_provenance()
    )
    prefix.load(session.name, "TEST")
    prefix.step(7)
    prefix_ts = prefix.snapshot()["replay"]["current_ts_ms"]

    assert full_events
    assert full_events == second.generated_pattern_events
    assert prefix.generated_pattern_events == [
        event for event in full_events if event["observation_ts_ms"] <= prefix_ts
    ]
    assert first.snapshot()["session"]["symbols"]["TEST"]["history_bars"] == []
    assert all(event["source_mode"] == SOURCE_MODE for event in full_events)
    assert all(
        event["replay_evidence"]["post_recording_history_used"] is False
        for event in full_events
    )


def test_sensitivity_views_remove_every_trigger_for_excluded_candidates():
    base = {
        "kind": "pattern_event",
        "symbol": "TEST",
        "pattern_type": "TIGHT_CONSOLIDATION_BREAKOUT",
        "state": "BREAKOUT",
    }
    events = [
        {
            **base,
            "event_id": "before",
            "pattern_start_ts_ms": 80_000,
            "observation_ts_ms": 90_000,
        },
        {
            **base,
            "event_id": "after",
            "pattern_start_ts_ms": 180_000,
            "observation_ts_ms": 180_000,
        },
        {
            **base,
            "event_id": "overlap",
            "pattern_start_ts_ms": 90_000,
            "observation_ts_ms": 500_000,
        },
        {
            **base,
            "event_id": "overlap-repeat",
            "pattern_start_ts_ms": 90_000,
            "observation_ts_ms": 510_000,
        },
        {
            **base,
            "event_id": "non-trigger",
            "state": "FORMING",
            "pattern_start_ts_ms": 90_000,
            "observation_ts_ms": 520_000,
        },
    ]
    for event in events:
        event["pattern_id"] = event["event_id"].replace("-repeat", "")
    excluded = [{"contributors": [{"pattern_id": "overlap"}]}]

    assert [
        event["event_id"]
        for event in _exclude_candidate_triggers(events, excluded)
    ] == [
        "before",
        "after",
        "non-trigger",
    ]


def test_group_summary_keeps_explicit_exclusion_accounting():
    trade = {
        "session_id": "session",
        "symbol": "TEST",
        "full_path": {
            "complete": True,
            "mfe_pct": 4.0,
            "mae_pct": -2.0,
            "mfe_r": 2.0,
            "mae_r": -1.0,
        },
        "exit_policy_results": {
            name: {
                "available": True,
                "realized_r": 2.0,
                "realized_pct": 4.0,
                "exit_reason": "TARGET",
            }
            for name in (
                "fixed_2r",
                "trail_after_2r_retrace_15pct",
                "trail_after_2r_retrace_20pct",
                "trail_after_2r_retrace_25pct",
            )
        },
    }
    record = {
        "session_id": "session",
        "trading_date": "2026-09-23",
        "symbols": ["TEST"],
        "generated_events": [],
        "candidates": [
            {"symbol": "TEST", "status": "SIMULATED", "reason": None},
            {
                "symbol": "TEST",
                "status": "SKIPPED_COOLDOWN",
                "reason": "candidate_triggered_during_cooldown",
            },
            {
                "symbol": "TEST",
                "status": "SKIPPED_NO_STOP",
                "reason": "no_detector_supported_stop_below_entry",
            },
        ],
        "trades": [trade],
        "all_simulated_trades_before_strict_path_filter": [trade],
        "inactivity_excluded_candidates": [{"symbol": "TEST"}],
        "gap_formation_excluded_candidates": [{"symbol": "TEST"}],
    }

    summary = _group_summary([record])

    assert summary["merged_candidate_count"] == 3
    assert summary["simulated_trade_count"] == 1
    assert summary["cooldown_exclusion_count"] == 1
    assert summary["missing_stop_exclusion_count"] == 1
    assert summary["status_inactivity_exclusion_count"] == 1
    assert summary["gap_data_quality_exclusion_count"] == 1
    assert summary["policies"]["fixed_2r"]["net_r"] == 2.0


def test_complete_pipeline_writes_overlays_without_changing_source(tmp_path):
    recordings = tmp_path / "recordings"
    _write_session(recordings)
    before = {
        path.relative_to(recordings): path.read_bytes()
        for path in recordings.rglob("*")
        if path.is_file()
    }

    first = build_replay_trade_baseline(
        recordings,
        tmp_path / "output-1",
        code_revision="a" * 40,
        start_date="2026-09-23",
        end_date="2026-09-23",
    )
    second = build_replay_trade_baseline(
        recordings,
        tmp_path / "output-2",
        code_revision="a" * 40,
        start_date="2026-09-23",
        end_date="2026-09-23",
    )
    after = {
        path.relative_to(recordings): path.read_bytes()
        for path in recordings.rglob("*")
        if path.is_file()
    }

    assert first == second
    assert before == after
    assert first["source_capture_integrity"]["byte_identical"] is True
    assert first["run_configuration"]["source_mode"] == SOURCE_MODE
    assert first["run_configuration"]["status_evidence"] == STATUS_EVIDENCE
    assert first["run_configuration"]["context_completeness"] == CONTEXT_COMPLETENESS
    for view in VIEWS:
        overlay = tmp_path / "output-1" / "overlays" / view / "2026-09-23_test"
        assert (overlay / "pattern_events.jsonl").exists()
        assert (overlay / "TEST.jsonl").is_symlink()
