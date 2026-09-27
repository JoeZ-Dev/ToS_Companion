from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TRIGGER_STATES = frozenset({"BREAKOUT", "CONTINUATION"})


def evidence_value(value: Any, *, source: str) -> dict[str, Any]:
    return {
        "available": value is not None,
        "value": value,
        "source": source if value is not None else None,
    }


def build_trigger_context(
    *,
    symbol_state: Mapping[str, Any],
    bar: Mapping[str, Any],
    observation_ts_ms: int,
) -> dict[str, Any]:
    quote = symbol_state.get("quote") or {}
    market = symbol_state.get("market_context") or {}
    ae = symbol_state.get("ae_snapshot") or {}
    derived = ae.get("derived") or {}
    fundamentals = ae.get("fundamentals") or {}
    session_levels = ae.get("session") or {}
    structural_levels = ae.get("levels") or {}
    quote_ts_ms = _int_or_none(quote.get("ts_ms"))
    context_as_of_ms = max(
        observation_ts_ms,
        quote_ts_ms if quote_ts_ms is not None else observation_ts_ms,
    )
    last = _number_or_none(quote.get("last"))
    price_source = "normalized_quote.last"
    if last is None:
        last = _number_or_none(bar.get("close"))
        price_source = "completed_bar.close"
    vwap = _number_or_none(ae.get("vwap"))
    distance_to_vwap = _number_or_none(derived.get("distance_to_vwap_pct"))

    return {
        "schema_version": 1,
        "captured_for_observation_ts_ms": int(observation_ts_ms),
        "context_as_of_ts_ms": context_as_of_ms,
        "price": evidence_value(last, source=price_source),
        "vwap": evidence_value(vwap, source="ae_snapshot.vwap"),
        "distance_to_vwap_pct": evidence_value(
            distance_to_vwap,
            source="ae_snapshot.derived.distance_to_vwap_pct",
        ),
        "day_change_pct": evidence_value(
            _number_or_none(quote.get("net_percentage_change")),
            source="schwab_level_one.net_percentage_change",
        ),
        "regular_market_change_pct": evidence_value(
            _number_or_none(quote.get("regular_market_percentage_change")),
            source="schwab_level_one.regular_market_percentage_change",
        ),
        "relative_strength": {
            "rank": evidence_value(
                market.get("relative_strength_rank"),
                source="watched_symbols.net_percentage_change_rank",
            ),
            "universe_size": evidence_value(
                market.get("relative_strength_universe_size"),
                source="watched_symbols.net_percentage_change_rank",
            ),
        },
        "security": {
            "status": evidence_value(
                quote.get("security_status"),
                source="schwab_level_one.security_status",
            ),
            "halted": evidence_value(
                quote.get("halted") if quote.get("security_status") is not None else None,
                source="normalized_quote.explicit_security_status",
            ),
        },
        "borrow": {
            "hard_to_borrow": evidence_value(
                quote.get("hard_to_borrow"),
                source="schwab_level_one.hard_to_borrow",
            ),
            "quantity": evidence_value(
                _number_or_none(quote.get("hard_to_borrow_quantity")),
                source="schwab_level_one.hard_to_borrow_quantity",
            ),
            "rate": evidence_value(
                _number_or_none(quote.get("hard_to_borrow_rate")),
                source="schwab_level_one.hard_to_borrow_rate",
            ),
            "shortable": evidence_value(
                quote.get("shortable"),
                source="schwab_level_one.shortable",
            ),
        },
        "fundamentals": {
            "shares_outstanding": evidence_value(
                _number_or_none(fundamentals.get("shares_outstanding")),
                source="ae_profile.fundamentals",
            ),
            "market_cap_float": evidence_value(
                _number_or_none(fundamentals.get("market_cap_float")),
                source="ae_profile.fundamentals",
            ),
            "short_interest_to_float": evidence_value(
                _number_or_none(fundamentals.get("short_interest_to_float")),
                source="ae_profile.fundamentals",
            ),
        },
        "session_phase": evidence_value(
            _session_phase(context_as_of_ms),
            source="America/New_York.session_clock",
        ),
        "volume": {
            "completed_bar": evidence_value(
                _number_or_none(bar.get("volume")),
                source="completed_bar.volume",
            ),
            "cumulative_day": evidence_value(
                _number_or_none(quote.get("volume")),
                source="schwab_level_one.total_volume",
            ),
            "ae_volume_multiple": evidence_value(
                _number_or_none((ae.get("volume") or {}).get("volume_multiple")),
                source="ae_snapshot.volume.volume_multiple",
            ),
        },
        "session_levels": {
            key: evidence_value(
                _number_or_none(session_levels.get(key)),
                source=f"ae_snapshot.session.{key}",
            )
            for key in (
                "premarket_high",
                "premarket_low",
                "opening_range_high",
                "opening_range_low",
                "open_price",
            )
        },
        "structural_levels": {
            "nearest_resistance": evidence_value(
                structural_levels.get("nearest_resistance"),
                source="ae_snapshot.levels.nearest_resistance",
            ),
            "nearest_support": evidence_value(
                structural_levels.get("nearest_support"),
                source="ae_snapshot.levels.nearest_support",
            ),
        },
    }


def _session_phase(timestamp_ms: int) -> str:
    local = datetime.fromtimestamp(timestamp_ms / 1000, tz=ET)
    minutes = local.hour * 60 + local.minute
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "PRE"
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "RTH"
    if 16 * 60 <= minutes <= 20 * 60:
        return "POST"
    return "CLOSED"


def _number_or_none(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
