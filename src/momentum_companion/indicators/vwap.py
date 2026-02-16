from __future__ import annotations

import pandas as pd


def compute_vwap_anchored(bars: pd.DataFrame, anchor_ts_utc: pd.Timestamp) -> pd.Series:
    """
    Compute VWAP anchored at 04:00 ET for the current day (specs.md §5.5).
    bars: DataFrame with columns ts_utc (datetime64[ns]), close, volume.
    """
    anchored = bars[bars["ts_utc"] >= anchor_ts_utc]
    if anchored.empty:
        return pd.Series(dtype=float)
    cum_vol = anchored["volume"].cumsum()
    cum_pv = (anchored["close"] * anchored["volume"]).cumsum()
    return cum_pv / cum_vol
