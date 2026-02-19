import pytest

pytest.importorskip("PySide6")

from momentum_companion.ui.chart_adapter import FakeChartAdapter


def test_fake_adapter_records_calls():
    adapter = FakeChartAdapter()
    bars = [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0}]
    adapter.set_history(bars)
    adapter.upsert_bar({"time": 2, "open": 2, "high": 2, "low": 2, "close": 2, "volume": 0})
    assert adapter.history == [bars]
    assert adapter.upserts[-1]["time"] == 2
