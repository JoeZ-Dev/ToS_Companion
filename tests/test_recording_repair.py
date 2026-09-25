import json
from pathlib import Path

import pytest

from momentum_companion.recording.repair import repair_recording_session


class FakeRest:
    def __init__(self, candles):
        self.candles = candles
        self.calls = []

    def fetch_price_history(self, symbol, start_ms, end_ms, freq):
        self.calls.append((symbol, start_ms, end_ms, freq))
        return {"candles": list(self.candles)}


def _write_session(tmp_path: Path, *, ended=True) -> tuple[Path, int]:
    session = tmp_path / "2026-09-25_073000_session"
    session.mkdir()
    manifest = {
        "schema_version": 1,
        "kind": "market_day_recording",
        "symbols": ["INLF"],
        "services": ["LEVELONE_EQUITIES"],
        "started_at_et": "2026-09-25T07:30:00-04:00",
        "ended_at_et": "2026-09-25T15:00:00-04:00" if ended else None,
        "counts": {"INLF": {"LEVELONE_EQUITIES": 2}},
    }
    (session / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    base = 1790335800000
    rows = [
        {
            "schema_version": 1,
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "INLF",
            "stream_ts_ms": base,
            "raw": {"key": "INLF", "1": 4.0, "2": 4.1, "3": 4.05, "8": 1000},
        },
        {
            "schema_version": 1,
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "INLF",
            "stream_ts_ms": base + 5 * 60_000,
            "raw": {"key": "INLF", "3": 4.55, "8": 5000},
        },
    ]
    (session / "INLF.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return session, base


def test_repair_preserves_original_and_builds_canonical_mixed_recording(tmp_path):
    session, base = _write_session(tmp_path)
    candles = [
        {
            "datetime": base + minute * 60_000,
            "open": 4.0 + minute / 10,
            "high": 4.1 + minute / 10,
            "low": 3.9 + minute / 10,
            "close": 4.05 + minute / 10,
            "volume": 1000 + minute,
        }
        for minute in range(1, 5)
    ]
    rest = FakeRest(candles)

    result = repair_recording_session(
        session,
        ["INLF"],
        rest,
        min_gap_seconds=90,
    )

    assert result["symbols"]["INLF"]["candles_inserted"] == 4
    assert (session / "INLF.jsonl.original").exists()

    canonical = [
        json.loads(line)
        for line in (session / "INLF.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["kind"] for row in canonical] == [
        "market_event",
        "historical_candle",
        "historical_candle",
        "historical_candle",
        "historical_candle",
        "market_event",
    ]
    assert [row["stream_ts_ms"] for row in canonical] == sorted(
        row["stream_ts_ms"] for row in canonical
    )
    assert all(
        row.get("source") == "SCHWAB_PRICEHISTORY_1M_GAP_REPAIR"
        for row in canonical
        if row["kind"] == "historical_candle"
    )

    manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
    repair = manifest["gap_repairs"]["INLF"]
    assert repair["status"] == "complete"
    assert repair["original_file"] == "INLF.jsonl.original"
    assert repair["canonical_file"] == "INLF.jsonl"


def test_repair_is_idempotent_and_uses_original_capture_as_source(tmp_path):
    session, base = _write_session(tmp_path)
    candles = [
        {
            "datetime": base + minute * 60_000,
            "open": 4.0,
            "high": 4.1,
            "low": 3.9,
            "close": 4.0,
            "volume": 100,
        }
        for minute in range(1, 5)
    ]
    rest = FakeRest(candles)

    repair_recording_session(session, ["INLF"], rest, min_gap_seconds=90)
    first = (session / "INLF.jsonl").read_text(encoding="utf-8")
    repair_recording_session(session, ["INLF"], rest, min_gap_seconds=90)
    second = (session / "INLF.jsonl").read_text(encoding="utf-8")

    assert second == first
    assert len(rest.calls) == 2


def test_repair_refuses_active_session(tmp_path):
    session, _ = _write_session(tmp_path, ended=False)

    with pytest.raises(RuntimeError, match="still active"):
        repair_recording_session(session, ["INLF"], FakeRest([]))
