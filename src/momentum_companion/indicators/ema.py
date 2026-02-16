from __future__ import annotations

import pandas as pd


def compute_ema(series: pd.Series, length: int) -> pd.Series:
    """Compute EMA with specified length."""
    return series.ewm(span=length, adjust=False).mean()
