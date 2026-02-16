from __future__ import annotations

from typing import FrozenSet

# Union of llm_coach.md glossary and specs.md §11.3.3 addendum.

BASE_GLOSSARY = frozenset(
    {
        "FAILED_BREAKOUT",
        "LOWER_HIGHS",
        "NO_CLEAR_LEVEL",
        "VWAP_TEST",
        "VWAP_REJECT",
        "VWAP_RECLAIM",
        "VOLUME_FADE",
        "WEAK_VOLUME_ON_EXTENSION",
        "STRONG_VOLUME_CONTINUATION",
        "BUYERS_WEAK",
        "HEAVY_SELL_PRESSURE",
        "HOD_BREAKOUT_HOLDING",
        "HOD_REJECT",
        "SPREAD_WIDENING",
        "THIN_LIQUIDITY",
        "RR_BELOW_MINIMUM",
        "DATA_STALE",
    }
)

ADDENDUM = frozenset(
    {
        "ENTRY_APPROACHING",
        "STOP_THREAT",
        "HALT_OR_REJECT",
        "DISCONNECT",
        "EXECUTION_FILL",
        "RISK_BREACH",
    }
)


def allowed_reason_codes() -> FrozenSet[str]:
    return BASE_GLOSSARY | ADDENDUM
