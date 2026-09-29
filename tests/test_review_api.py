import json

import pytest
from pathlib import Path

from momentum_companion.review import ReviewAnnotationStore, ReviewCorpus


def _write_session(root: Path) -> Path:
    session = root / "2026-09-23_070000_session"
    session.mkdir(parents=True)
    (session / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "kind": "market_day_recording",
        "symbols": ["TOPS"],
        "services": ["LEVELONE_EQUITIES"],
        "started_at_et": "2026-09-23T07:00:00-04:00",
        "ended_at_et": "2026-09-23T07:30:00-04:00",
        "counts": {"TOPS": {"LEVELONE_EQUITIES": 4}},
    }))
    base = 1_790_161_200_000
    rows = [
        {"kind":"market_event","service":"LEVELONE_EQUITIES","symbol":"TOPS","stream_ts_ms":base,
         "raw":{"key":"TOPS","1":1.00,"2":1.02,"3":1.01,"8":1000}},
        {"kind":"market_event","service":"LEVELONE_EQUITIES","symbol":"TOPS","stream_ts_ms":base+10_000,
         "raw":{"key":"TOPS","3":1.03,"8":1200}},
        {"kind":"market_event","service":"LEVELONE_EQUITIES","symbol":"TOPS","stream_ts_ms":base+20_000,
         "raw":{"key":"TOPS","3":1.05,"8":1500}},
        {"kind":"market_event","service":"LEVELONE_EQUITIES","symbol":"TOPS","stream_ts_ms":base+30_000,
         "raw":{"key":"TOPS","3":0.98,"8":1900}},
    ]
    with (session / "TOPS.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return session


def test_review_window_contains_only_evidence_through_requested_end(tmp_path):
    session = _write_session(tmp_path)
    corpus = ReviewCorpus(tmp_path)
    base = 1_790_161_200_000

    packet = corpus.window(
        session.name,
        "TOPS",
        start_ms=base,
        end_ms=base + 20_000,
    )

    assert packet["window"]["future_data_included"] is False
    assert packet["replay"]["current_ts_ms"] == base + 20_000
    assert packet["end_state"]["quote"]["last"] == 1.05
    assert all(bar["ts"] * 1000 <= base + 20_000 for bar in packet["bars_10s"])


def test_verification_window_never_includes_post_trigger_price(tmp_path):
    session = _write_session(tmp_path)
    corpus = ReviewCorpus(tmp_path)
    base = 1_790_161_200_000

    packet = corpus.verification_window(
        session.name,
        "TOPS",
        trigger_ms=base + 20_000,
        lookback_ms=20_000,
    )

    assert packet["window"]["end_ms"] == base + 20_000
    assert packet["end_state"]["quote"]["last"] == 1.05
    assert packet["end_state"]["quote"]["last"] != 0.98


def test_review_window_rejects_oversized_request(tmp_path):
    session = _write_session(tmp_path)
    corpus = ReviewCorpus(tmp_path)
    base = 1_790_161_200_000

    try:
        corpus.window(
            session.name,
            "TOPS",
            start_ms=base,
            end_ms=base + 46 * 60 * 1000,
        )
    except ValueError as exc:
        assert "45 minutes" in str(exc)
    else:
        raise AssertionError("oversized review window must be rejected")


def test_annotations_are_append_only_and_separate_from_recordings(tmp_path):
    recordings = tmp_path / "recordings"
    _write_session(recordings)
    store = ReviewAnnotationStore(tmp_path / "review_annotations")

    saved = store.add({
        "session_id": "2026-09-23_070000_session",
        "symbol": "tops",
        "setup_type": "ascending_triangle",
        "trigger_ms": 1_790_161_220_000,
        "valid_at_time": True,
        "outcome": "failed",
        "confidence": 0.84,
        "evidence": {"resistance": 1.05},
    })

    assert saved["symbol"] == "TOPS"
    assert saved["annotation_id"]
    assert store.list(symbol="TOPS")[0]["outcome"] == "failed"
    assert not (recordings / "annotations.jsonl").exists()


def test_review_window_before_first_event_returns_empty_availability_packet(tmp_path):
    session = _write_session(tmp_path)
    corpus = ReviewCorpus(tmp_path)
    base = 1_790_161_200_000

    packet = corpus.window(
        session.name,
        "TOPS",
        start_ms=base - 20 * 60 * 1000,
        end_ms=base - 10 * 60 * 1000,
    )

    assert packet["window"]["future_data_included"] is False
    assert packet["window"]["availability"]["status"] == "before_recording"
    assert packet["window"]["availability"]["events_in_window"] == 0
    assert packet["bars_10s"] == []
    assert packet["end_state"]["quote"]["last"] is None
    assert packet["replay"]["cursor"] == 0


def test_review_context_marks_first_five_minutes_very_high_volatility():
    context = ReviewCorpus._review_context(1_790_170_380_000)

    assert context["opening_volatility_context"] == "very_high"
    assert context["opening_structure_rule"] is True


def test_review_context_marks_0935_to_0945_elevated():
    context = ReviewCorpus._review_context(1_790_170_800_000)

    assert context["opening_volatility_context"] == "elevated"
    assert context["opening_structure_rule"] is True


def test_review_context_returns_normal_after_opening_window():
    context = ReviewCorpus._review_context(1_790_171_400_000)

    assert context["opening_volatility_context"] == "normal"
    assert context["opening_structure_rule"] is False


def test_l1_window_carries_forward_prior_quote_state(tmp_path):
    session = _write_session(tmp_path)
    corpus = ReviewCorpus(tmp_path)
    base = 1_790_161_200_000

    packet = corpus.l1_window(
        session.name,
        "TOPS",
        start_ms=base + 10_000,
        end_ms=base + 20_000,
    )

    assert packet["window"]["future_data_included"] is False
    assert packet["window"]["events_in_window"] == 2
    assert [frame["timestamp_ms"] for frame in packet["frames"]] == [
        base + 10_000,
        base + 20_000,
    ]
    assert packet["frames"][0]["bid"] == 1.00
    assert packet["frames"][0]["ask"] == 1.02
    assert packet["frames"][0]["last"] == 1.03
    assert packet["frames"][1]["last"] == 1.05
    assert packet["frames"][1]["spread"] == pytest.approx(0.02)


def test_l1_window_never_includes_event_after_requested_end(tmp_path):
    session = _write_session(tmp_path)
    corpus = ReviewCorpus(tmp_path)
    base = 1_790_161_200_000

    packet = corpus.l1_window(
        session.name,
        "TOPS",
        start_ms=base,
        end_ms=base + 20_000,
    )

    assert all(
        frame["timestamp_ms"] <= base + 20_000
        for frame in packet["frames"]
    )
    assert all(frame["last"] != 0.98 for frame in packet["frames"])


def test_l1_window_rejects_more_than_two_minutes(tmp_path):
    session = _write_session(tmp_path)
    corpus = ReviewCorpus(tmp_path)
    base = 1_790_161_200_000

    try:
        corpus.l1_window(
            session.name,
            "TOPS",
            start_ms=base,
            end_ms=base + 121_000,
        )
    except ValueError as exc:
        assert "120 seconds" in str(exc)
    else:
        raise AssertionError("oversized L1 review window must be rejected")
