import json

import pytest

from momentum_companion.evaluation.research_export import build_research_export


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _build_session(tmp_path):
    session = tmp_path / "session"
    session.mkdir(parents=True)
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "kind": "market_day_recording",
                "symbols": ["AEHL"],
                "provenance": {
                    "application": {"git_revision": "a" * 40},
                    "pattern_evaluation": {"bar_cadence_seconds": 10},
                },
                "derived_artifacts": {
                    "pattern_events": {"path": "pattern_events.jsonl"},
                    "security_status_events": {
                        "path": "security_status_events.jsonl"
                    },
                },
            }
        )
    )
    _write_jsonl(
        session / "pattern_events.jsonl",
        [
            {
                "kind": "pattern_event",
                "event_id": "a1",
                "session_id": "session",
                "symbol": "AEHL",
                "pattern_id": "a",
                "pattern_type": "ASCENDING_TRIANGLE",
                "state": "VALID",
                "pattern_start_ts_ms": 80_000,
                "observation_ts_ms": 100_000,
                "evidence": {"resistance": 10.0},
                "geometry": {"points": [], "lines": []},
            },
            {
                "kind": "pattern_event",
                "event_id": "b1",
                "session_id": "session",
                "symbol": "AEHL",
                "pattern_id": "b",
                "pattern_type": "LOCAL_RESISTANCE_BREAKOUT",
                "state": "VALID",
                "pattern_start_ts_ms": 90_000,
                "observation_ts_ms": 110_000,
                "evidence": {"resistance": 10.01},
                "geometry": {"points": [], "lines": []},
            },
            {
                "kind": "pattern_event",
                "event_id": "a2",
                "session_id": "session",
                "symbol": "AEHL",
                "pattern_id": "a",
                "pattern_type": "ASCENDING_TRIANGLE",
                "state": "BREAKOUT",
                "pattern_start_ts_ms": 80_000,
                "observation_ts_ms": 120_000,
                "evidence": {"resistance": 10.0},
                "geometry": {"points": [], "lines": []},
                "trigger_context": {"price": {"available": True, "value": 10.1}},
            },
        ],
    )
    _write_jsonl(
        session / "security_status_events.jsonl",
        [
            {
                "kind": "security_status_event",
                "event_id": "status",
                "symbol": "AEHL",
                "provider_status": "Normal",
                "provider_ts_ms": 90_000,
                "observed_ts_ms": 91_000,
            }
        ],
    )
    (session / "AEHL.jsonl").write_text("")
    return session


def test_export_composes_trigger_evidence_status_overlap_and_integrity(tmp_path):
    recordings = tmp_path / "recordings"
    _build_session(recordings)

    report = build_research_export(
        recordings,
        session_id="session",
        symbol="aehl",
        pattern_type="ascending_triangle",
        has_trigger=True,
    )

    assert report["future_data_policy"]["blind_review_safe"] is False
    assert report["future_data_policy"]["outcomes_included"] is False
    assert report["summary"]["pattern_instance_count"] == 1
    exported = report["sessions"][0]
    assert "outcome_measurements" not in exported
    assert exported["provenance"]["application"]["git_revision"] == "a" * 40
    assert exported["integrity"]["symbols"]["AEHL"]["raw_event_count"] == 0
    pattern = exported["patterns"][0]
    assert len(pattern["state_transition_journal"]) == 2
    assert pattern["state_transition_journal"][1]["trigger_context"]["price"]["value"] == 10.1
    assert pattern["status_context"]["at_triggers"][0]["latest_explicit_status"]["provider_status"] == "Normal"
    assert len(exported["overlaps"]) == 1
    assert pattern["overlap_ids"] == [exported["overlaps"][0]["overlap_id"]]


def test_outcomes_are_opt_in_and_remain_in_separate_section(tmp_path, monkeypatch):
    recordings = tmp_path / "recordings"
    _build_session(recordings)
    monkeypatch.setattr(
        "momentum_companion.evaluation.research_export.build_pattern_outcomes",
        lambda *args, **kwargs: {
            "horizon_ms": 900_000,
            "forward_minutes": [1, 2, 5, 10, 15],
            "outcomes": [{"pattern_id": "a", "excursion": {"mfe_pct": 5.0}}],
        },
    )

    report = build_research_export(
        recordings,
        session_id="session",
        pattern_type="ASCENDING_TRIANGLE",
        include_outcomes=True,
    )

    session = report["sessions"][0]
    assert report["future_data_policy"]["outcomes_included"] is True
    assert session["patterns"][0].get("outcome") is None
    assert session["outcome_measurements"]["outcomes"][0]["excursion"]["mfe_pct"] == 5.0


def test_export_filters_corpus_time_and_validates_requests(tmp_path):
    recordings = tmp_path / "recordings"
    _build_session(recordings)
    (tmp_path / "corpus_classifications.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sessions": {
                    "session": {
                        "classification": "holdout",
                        "classified_at_utc": "2026-09-27T12:00:00Z",
                        "note": None,
                        "history": [],
                    }
                },
            }
        )
    )

    included = build_research_export(
        recordings,
        corpus_classification="holdout",
        start_ms=110_000,
        end_ms=120_000,
    )
    excluded = build_research_export(
        recordings,
        corpus_classification="development",
    )

    assert included["summary"]["session_count"] == 1
    assert included["summary"]["pattern_instance_count"] == 2
    assert excluded["summary"]["session_count"] == 0
    with pytest.raises(ValueError, match="less than or equal"):
        build_research_export(recordings, start_ms=2, end_ms=1)
    with pytest.raises(ValueError, match="corpus_classification"):
        build_research_export(recordings, corpus_classification="mystery")
