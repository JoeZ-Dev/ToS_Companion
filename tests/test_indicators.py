import pytest

pd = pytest.importorskip("pandas")

from momentum_companion.indicators.engine import IndicatorsEngine


def test_indicators_engine_outputs_vwap_and_emas():
    bars = pd.DataFrame(
        {
            "ts_utc": pd.to_datetime(
                ["2026-02-08T09:00:00Z", "2026-02-08T09:00:10Z", "2026-02-08T09:00:20Z"]
            ),
            "close": [10.0, 12.0, 11.0],
            "volume": [100, 200, 100],
        }
    )
    engine = IndicatorsEngine()
    anchor = pd.Timestamp("2026-02-08T09:00:00Z")
    studies = engine.compute_studies(bars, anchor)
    assert "vwap" in studies and "ema9" in studies and "ema20" in studies
