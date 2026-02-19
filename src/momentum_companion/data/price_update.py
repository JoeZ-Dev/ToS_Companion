from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class PriceUpdate:
    """Normalized price event used by aggregators and chart pipeline."""

    timestamp: int  # epoch seconds (UTC)
    price: float
    size: Optional[float]  # cumulative vol for L1; trade size for TNS
    source: Literal["L1", "TNS"]
