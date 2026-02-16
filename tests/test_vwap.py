import pytest

pd = pytest.importorskip("pandas")

from momentum_companion.indicators.vwap import compute_vwap_anchored


def test_vwap_anchored():
    data = pd.DataFrame(
        {
            "ts_utc": pd.to_datetime(
                [
                    "2026-02-08T09:00:00Z",
                    "2026-02-08T10:00:00Z",
                    "2026-02-08T11:00:00Z",
                ]
            ),
            "close": [10.0, 12.0, 11.0],
            "volume": [100, 200, 100],
        }
    )
    anchor = pd.Timestamp("2026-02-08T09:00:00Z")
    vwap = compute_vwap_anchored(data, anchor)
    assert round(vwap.iloc[-1], 2) == 11.25
