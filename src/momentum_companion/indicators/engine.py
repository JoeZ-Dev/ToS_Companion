from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from momentum_companion.indicators.vwap import compute_vwap_anchored
from momentum_companion.indicators.ema import compute_ema


class IndicatorsEngine:
    """Computes VWAP and EMA overlays for chart display per specs.md §5.5."""

    def compute_studies(self, bars_10s: pd.DataFrame, anchor_ts_utc: pd.Timestamp) -> Dict[str, Any]:
        """Return study values keyed by study name."""
        vwap = compute_vwap_anchored(bars_10s, anchor_ts_utc)
        ema9 = compute_ema(bars_10s["close"], 9) if "close" in bars_10s else pd.Series(dtype=float)
        ema20 = compute_ema(bars_10s["close"], 20) if "close" in bars_10s else pd.Series(dtype=float)
        studies: Dict[str, Any] = {"vwap": vwap, "ema9": ema9, "ema20": ema20}
        return studies
