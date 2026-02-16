import pytest

pd = pytest.importorskip("pandas")

from momentum_companion.data.bar_aggregator import BarAggregator10s


def test_is_extended_premarket():
    agg = BarAggregator10s()
    # 05:00 ET is premarket (assuming 2026-02-08; UTC 10:00)
    dt = pd.Timestamp("2026-02-08T10:00:00Z")
    ts_ms = int(dt.timestamp() * 1000)
    assert agg._is_extended(ts_ms) is True


def test_is_extended_regular():
    agg = BarAggregator10s()
    dt = pd.Timestamp("2026-02-08T15:00:00Z")  # 10:00 ET
    ts_ms = int(dt.timestamp() * 1000)
    assert agg._is_extended(ts_ms) is False
