from momentum_companion.recording.pattern_replay import PatternReplayRunner
from momentum_companion.setup_engine.pattern_contracts import PatternObservation, PatternState
from momentum_companion.setup_engine.pattern_engine import PatternEngine
from momentum_companion.setup_engine.pattern_service import PatternEvaluationService


class EveryBarDetector:
    name = "EVERY_BAR"

    def detect(self, symbol, bars):
        materialized = list(bars)
        if not materialized:
            return None
        last = materialized[-1]
        ts = last.get("ts", last.get("time"))
        return PatternObservation(
            symbol=symbol,
            pattern_type=self.name,
            state=PatternState.FORMING,
            started_at=ts,
            updated_at=ts,
            evidence={"bars_seen": len(materialized)},
        )


def record(ts_ms, last, volume, *, symbol="ABCD", include_full_quote=True):
    raw = {
        "key": symbol,
        "3": last,
        "8": volume,
    }
    if include_full_quote:
        raw.update({"1": last - 0.01, "2": last + 0.01})
    return {
        "schema_version": 1,
        "kind": "market_event",
        "service": "LEVELONE_EQUITIES",
        "symbol": symbol,
        "stream_ts_ms": ts_ms,
        "received_at": "2026-09-22T13:30:00Z",
        "raw": raw,
    }


def runner():
    engine = PatternEngine()
    engine.register(EveryBarDetector())
    return PatternReplayRunner(
        pattern_service=PatternEvaluationService(engine=engine)
    )


def test_replay_builds_completed_10s_bars_and_feeds_pattern_service():
    replay = runner()

    snapshot = replay.replay_records(
        [
            record(1_800_000_000_000, 10.00, 1000),
            record(1_800_000_005_000, 10.10, 1050, include_full_quote=False),
            record(1_800_000_010_000, 10.20, 1100, include_full_quote=False),
            record(1_800_000_020_000, 10.30, 1200, include_full_quote=False),
        ]
    )

    state = snapshot["symbols"]["ABCD"]
    assert len(state["completed_bars"]) == 2
    assert state["completed_bars"][0]["open"] == 10.00
    assert state["completed_bars"][0]["high"] == 10.10
    assert state["completed_bars"][0]["close"] == 10.10
    assert state["patterns"][0]["pattern_type"] == "EVERY_BAR"
    assert state["patterns"][0]["evidence"]["bars_seen"] == 2


def test_replay_uses_level_one_cache_for_delta_records():
    replay = runner()

    replay.feed_record(record(1_800_000_000_000, 5.00, 1000))
    replay.feed_record(record(1_800_000_010_000, 5.10, 1010, include_full_quote=False))
    replay.feed_record(record(1_800_000_020_000, 5.20, 1020, include_full_quote=False))

    bars = replay.snapshot()["symbols"]["ABCD"]["completed_bars"]
    assert [bar["close"] for bar in bars] == [5.00, 5.10]


def test_replay_ignores_non_l1_and_malformed_records():
    replay = runner()

    assert replay.feed_record({"kind": "manifest"}) == []
    assert replay.feed_record({
        "kind": "market_event",
        "service": "TIMESALE_EQUITY",
        "symbol": "ABCD",
        "stream_ts_ms": 1,
        "raw": {},
    }) == []
    assert replay.snapshot()["symbols"] == {}


def test_replay_keeps_symbols_isolated():
    replay = runner()
    records = [
        record(1_800_000_000_000, 10.0, 1000, symbol="AAA"),
        record(1_800_000_000_000, 20.0, 2000, symbol="BBB"),
        record(1_800_000_010_000, 10.1, 1010, symbol="AAA", include_full_quote=False),
        record(1_800_000_010_000, 20.1, 2010, symbol="BBB", include_full_quote=False),
        record(1_800_000_020_000, 10.2, 1020, symbol="AAA", include_full_quote=False),
        record(1_800_000_020_000, 20.2, 2020, symbol="BBB", include_full_quote=False),
    ]

    snapshot = replay.replay_records(records)

    assert set(snapshot["symbols"]) == {"AAA", "BBB"}
    assert snapshot["symbols"]["AAA"]["completed_bars"][0]["close"] == 10.0
    assert snapshot["symbols"]["BBB"]["completed_bars"][0]["close"] == 20.0
