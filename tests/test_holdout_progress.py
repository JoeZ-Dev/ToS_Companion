from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from momentum_companion.evaluation.holdout_progress import (
    audit_capture_date,
    build_progress_report,
    load_date_manifest,
    load_outcome_blind_inventory,
)


ET = ZoneInfo("America/New_York")


def _manifest() -> dict:
    return {
        "kind": "prospective_holdout_date_manifest",
        "recorded_before_outcome_review": True,
        "dates": [
            {
                "trading_date": "2026-09-30", "status": "excluded",
                "classification": "excluded_partial_capture",
                "reason": "authorization/deployment interruption",
                "counts_toward": {"trading_dates": False, "opportunities": False,
                                  "paired_trades": False, "performance": False},
            },
            {
                "trading_date": "2026-10-01", "status": "pending",
                "classification": "pending_capture_completion",
                "reason": "pending", "counts_toward": {"trading_dates": False,
                "opportunities": False, "paired_trades": False, "performance": False},
            },
            {
                "trading_date": "2026-10-02", "status": "included",
                "classification": "complete_capture", "reason": "complete",
                "counts_toward": {"trading_dates": True, "opportunities": True,
                "paired_trades": True, "performance": True},
            },
        ],
    }


def _row(day: str, opportunity: str, *, baseline=True, confirmed=True) -> dict:
    return {
        "trading_date": day, "opportunity_id": opportunity,
        "baseline_entered": baseline, "confirmed_entered": confirmed,
        "momentum_evidence": "available",
        "momentum_eligibility": "trade_candidate",
    }


def test_september_30_is_excluded_for_the_locked_reason() -> None:
    report = build_progress_report(_manifest(), [_row("2026-09-30", "X")])
    assert report["dates"]["excluded"] == [{
        "trading_date": "2026-09-30",
        "classification": "excluded_partial_capture",
        "reason": "authorization/deployment interruption",
    }]
    assert report["counts"]["grouped_opportunities"] == 0


def test_pending_october_1_and_incomplete_dates_do_not_count() -> None:
    report = build_progress_report(
        _manifest(), [_row("2026-10-01", "PENDING"), _row("2026-10-02", "INCLUDED")]
    )
    assert report["dates"]["pending"] == ["2026-10-01"]
    assert report["counts"]["grouped_opportunities"] == 1
    assert report["progress"]["independent_trading_dates"]["observed"] == 1


def test_opportunity_deduplication_is_scoped_to_exact_date() -> None:
    manifest = _manifest()
    manifest["dates"].append({
        "trading_date": "2026-10-03", "status": "included",
        "classification": "complete_capture", "reason": "complete",
        "counts_toward": {"trading_dates": True, "opportunities": True,
                          "paired_trades": True, "performance": True},
    })
    report = build_progress_report(manifest, [
        _row("2026-10-02", "SAME"), _row("2026-10-02", "SAME"),
        _row("2026-10-03", "SAME"),
    ])
    assert report["counts"]["grouped_opportunities"] == 2
    assert report["counts"]["baseline_confirmed_paired_opportunities"] == 2


def test_duplicate_manifest_date_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["dates"].append(dict(manifest["dates"][-1]))
    path = tmp_path / "dates.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate exact trading date"):
        load_date_manifest(path)


@pytest.mark.parametrize("key", ["realized_r", "wins", "exit_reason", "expectancy"])
def test_outcome_fields_are_rejected_and_absent_from_report(tmp_path: Path, key: str) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"opportunities": [{**_row("2026-10-02", "X"), key: 1}]}))
    with pytest.raises(ValueError, match="outcome field is forbidden"):
        load_outcome_blind_inventory(path)
    report = build_progress_report(_manifest(), [_row("2026-10-02", "X")])
    encoded = json.dumps(report).lower()
    for forbidden in ("realized_r", "wins", "losses", "exit_reason", "expectancy", "net_r"):
        assert forbidden not in encoded


def test_capture_audit_is_read_only_and_reports_no_october_session(tmp_path: Path) -> None:
    before = _tree_hashes(tmp_path)
    result = audit_capture_date(
        tmp_path, "2026-10-01",
        now=datetime(2026, 10, 1, 11, 0, tzinfo=ET),
    )
    after = _tree_hashes(tmp_path)
    assert result["disposition"] == "exclude_candidate"
    assert result["reason"] == "no_recording_sessions"
    assert before == after


def test_capture_audit_keeps_october_1_pending_before_required_end(tmp_path: Path) -> None:
    result = audit_capture_date(
        tmp_path, "2026-10-01",
        now=datetime(2026, 10, 1, 8, 49, tzinfo=ET),
    )
    assert result["disposition"] == "pending"
    assert result["reason"] == "required_window_not_complete"


def test_raw_recordings_remain_unchanged_during_progress(tmp_path: Path) -> None:
    session = tmp_path / "2026-10-02_065959_session"
    session.mkdir()
    raw = session / "XYZ.jsonl"
    raw.write_text('{"kind":"market_event","stream_ts_ms":1790942400000}\n')
    before = _tree_hashes(tmp_path)
    build_progress_report(_manifest(), [_row("2026-10-02", "X")])
    after = _tree_hashes(tmp_path)
    assert before == after


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }
