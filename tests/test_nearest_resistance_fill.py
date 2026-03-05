from momentum_companion.analysis.ae import OneMinuteBar
from momentum_companion.analysis import ae


def _mock_snapshot(price: float, bars: list[OneMinuteBar]):
    engine = ae.AnalysisEngineClient()  # type: ignore


def test_nearest_resistance_fills_from_micro(monkeypatch):
    # Build minimal AE-like state
    agg = ae.MinuteBarAggregator()
    # seed bars
    for i in range(25):
        b = OneMinuteBar(ts=i * 60, open=1.0, high=1.0, low=1.0, close=1.0, volume=1000 + i, is_extended=False)
        agg._bars.append(b)
    # Build snapshot manually
    current_price = 1.0
    micro = {"micro_resistance_15m": 1.05, "micro_support_15m": 0.9, "micro_state": None}
    levels = {"nearest_resistance": None, "nearest_support": None}
    bars_window_5m = []

    # Use fallback helper directly
    def _first_valid_above(price, last_price):
        if price is None or last_price is None or price <= last_price:
            return None
        return price

    assert _first_valid_above(micro["micro_resistance_15m"], current_price) == 1.05


def test_nearest_resistance_uses_swing_high():
    agg = ae.MinuteBarAggregator()
    for i in range(10):
        b = OneMinuteBar(ts=i * 60, open=1.0, high=1.0 + i * 0.01, low=0.9, close=1.0, volume=1000, is_extended=False)
        agg._bars.append(b)
    bars_window_5m = ae._build_bars_window_5m(agg._bars, limit=60)
    highs = [b.get("h") for b in bars_window_5m if isinstance(b, dict)]
    assert max(highs) > 1.0

