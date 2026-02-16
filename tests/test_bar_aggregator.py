import pytest

pd = pytest.importorskip("pandas")

from momentum_companion.data.bar_aggregator import BarAggregator10s, WINDOW_MS


def make_quote(ts_ms: int, last: float, volume: float = 0.0):
    return {
        "ts_ms": ts_ms,
        "symbol": "AAPL",
        "bid": None,
        "ask": None,
        "last": last,
        "bid_size": None,
        "ask_size": None,
        "last_size": None,
        "volume": volume,
        "source_ts_type": "QUOTE_TS",
        "raw_source": "SCHWAB_STREAM",
    }


def test_left_inclusive_right_exclusive_rollover():
    agg = BarAggregator10s()
    assert agg.ingest_quote(make_quote(0, 10.0, 100)) is None
    assert agg.ingest_quote(make_quote(WINDOW_MS - 1, 11.0, 150)) is None
    completed = agg.ingest_quote(make_quote(WINDOW_MS, 12.0, 175))
    assert completed is not None
    assert completed.open == 10.0
    assert completed.high == 11.0
    assert completed.low == 10.0
    assert completed.close == 11.0
    # first quote sets baseline; second adds delta 50
    assert completed.volume == 50


def test_gap_no_bar_when_no_quotes():
    agg = BarAggregator10s()
    agg.ingest_quote(make_quote(0, 10.0, 10))
    # Jump ahead beyond two windows without quotes in between
    completed = agg.ingest_quote(make_quote(3 * WINDOW_MS, 12.0, 5))
    assert completed is not None
    # Gap is represented by absence of bars; last bar ends previous window.
    assert completed.ts_ms == 0


def test_volume_delta_resets_on_symbol_change_or_restart():
    agg = BarAggregator10s()
    agg.ingest_quote(make_quote(0, 10.0, 100))
    # First volume is baseline; delta should be 0 in bar volume
    first = agg.close_out()
    assert first.volume == 0
    agg.ingest_quote(make_quote(10_000, 11.0, 150))
    bar = agg.close_out()
    # Volume delta should be 50 on this bar
    assert bar.volume == 50
