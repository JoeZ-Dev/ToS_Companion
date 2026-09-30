from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from momentum_companion.setup_engine.structure.volume import (
    current_volume_expansion,
    recent_volume_stats,
    volume_trend,
)
from momentum_companion.setup_engine.structure.session_levels import (
    SessionLevelConfig,
    session_level_context,
)

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
    raw_quote = symbol_state.get("quote") or {}
    ae = symbol_state.get("ae_snapshot") or {}
    derived = ae.get("derived") or {}
    fundamentals = ae.get("fundamentals") or {}
    session_levels = ae.get("session") or {}
    structural_levels = ae.get("levels") or {}
    completed_bars = list(symbol_state.get("bars_10s") or [])
    prior_bars = completed_bars[:-1]
    recent_stats = recent_volume_stats(prior_bars, lookback=20)
    trend = volume_trend(prior_bars, lookback=20)
    quote_ts_ms = _int_or_none(raw_quote.get("ts_ms"))
    quote_is_bounded = (
        quote_ts_ms is not None and quote_ts_ms <= int(observation_ts_ms)
    )
    quote = raw_quote if quote_is_bounded else {}
    market = (symbol_state.get("market_context") or {}) if quote_is_bounded else {}
    context_as_of_ms = int(observation_ts_ms)
    last = _number_or_none(quote.get("last"))
    price_source = "normalized_quote.last"
    if last is None:
        last = _number_or_none(bar.get("close"))
        price_source = "completed_bar.close"
    vwap = _number_or_none(ae.get("vwap"))
    distance_to_vwap = _number_or_none(derived.get("distance_to_vwap_pct"))
    standardized_session = session_level_context(
        [
            *(symbol_state.get("history_bars") or []),
            *completed_bars,
        ],
        as_of_ts=context_as_of_ms // 1000,
        current_price=last,
        vwap=vwap,
        config=SessionLevelConfig(opening_range_minutes=10),
    )
    standardized_levels = dict(standardized_session["levels"])
    standardized_distances = dict(standardized_session["distances_pct"])
    standardized_sources = {
        key: "session_level_primitive" for key in standardized_levels
    }
    for key in (
        "premarket_high",
        "premarket_low",
        "opening_range_high",
        "opening_range_low",
    ):
        if standardized_levels[key] is not None:
            continue
        legacy_value = _number_or_none(session_levels.get(key))
        if legacy_value is not None:
            standardized_levels[key] = legacy_value
            standardized_distances[key] = _distance_pct(last, legacy_value)
            standardized_sources[key] = f"ae_snapshot.session.{key}"

    context = {
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
            "recent_mean_20": evidence_value(
                recent_stats["mean"],
                source="volume_primitive.recent_mean_20",
            ),
            "recent_median_20": evidence_value(
                recent_stats["median"],
                source="volume_primitive.recent_median_20",
            ),
            "current_expansion_ratio_20": evidence_value(
                current_volume_expansion(bar, prior_bars, lookback=20),
                source="volume_primitive.current_expansion_ratio_20",
            ),
            "trend_slope_20": evidence_value(
                trend["slope_per_bar"],
                source="volume_primitive.trend_slope_20",
            ),
            "trend_direction_20": evidence_value(
                trend["direction"],
                source="volume_primitive.trend_direction_20",
            ),
        },
        "session_levels": {
            **{
                key: evidence_value(
                    _number_or_none(value),
                    source=standardized_sources[key],
                )
                for key, value in standardized_levels.items()
            },
            "open_price": evidence_value(
                _number_or_none(session_levels.get("open_price")),
                source="ae_snapshot.session.open_price",
            ),
            "distances_pct": {
                key: evidence_value(
                    _number_or_none(value),
                    source="session_level_primitive",
                )
                for key, value in standardized_distances.items()
            },
            "opening_range_minutes": standardized_session["opening_range_minutes"],
            "opening_range_complete": standardized_session["opening_range_complete"],
            "timezone": standardized_session["timezone"],
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
    context["resistance_registry"] = _resistance_registry(
        context=context,
        proposed_entry=last,
        observation_ts_ms=context_as_of_ms,
        micro_resistance=_number_or_none((ae.get("micro") or {}).get("micro_resistance_15m")),
        prior_bars=prior_bars,
    )
    return context


def attach_detector_resistance_evidence(
    context: Mapping[str, Any], observation: Mapping[str, Any]
) -> dict[str, Any]:
    """Add detector structural evidence without changing detector evaluation."""
    enriched = dict(context)
    registry = dict(enriched.get("resistance_registry") or {})
    candidates = [dict(item) for item in registry.get("candidates") or []]
    entry = _evidence_number((enriched.get("price") or {}))
    as_of = int(enriched.get("context_as_of_ts_ms") or observation.get("updated_at") or 0)
    detector_values = []
    for key, raw in sorted((observation.get("evidence") or {}).items()):
        if not any(token in str(key).lower() for token in ("resistance", "breakout_level", "range_high", "swing_high")):
            continue
        value = _number_or_none(raw)
        if value is not None:
            detector_values.append((str(key), value))
    if detector_values:
        broken_prices = {
            value for key, value in detector_values
            if "breakout" in key.lower() or "resistance" in key.lower()
        }
        for candidate in candidates:
            price = _number_or_none(candidate.get("price"))
            if price is not None and any(abs(price - broken) <= 1e-9 for broken in broken_prices):
                candidate["role"] = "broken_level"
        for key, value in detector_values:
            candidates.append(_candidate(
                source_type=f"detector_structural_resistance:{key}", price=value,
                entry=entry, as_of=as_of, available=True,
                role="broken_level" if "breakout" in key or "resistance" in key else "candidate",
            ))
    else:
        candidates.append(_candidate(
            source_type="detector_structural_resistance", price=None,
            entry=entry, as_of=as_of, available=False,
        ))
    enriched["resistance_registry"] = _finalize_registry(candidates, entry, as_of)
    return enriched


def _resistance_registry(*, context, proposed_entry, observation_ts_ms, micro_resistance, prior_bars):
    session = context.get("session_levels") or {}
    mapping = (
        ("premarket_high", "PMH"),
        ("opening_range_high", "ORH"),
        ("regular_session_high", "regular_session_high"),
        ("vwap", "VWAP"),
        ("prior_day_high", "prior_day_high"),
    )
    candidates = []
    for key, label in mapping:
        raw = session.get(key) or {}
        value = _evidence_number(raw)
        candidates.append(_candidate(
            source_type=label, price=value, entry=proposed_entry,
            as_of=observation_ts_ms, available=bool(raw.get("available")) and value is not None,
        ))
    candidates.append(_candidate(
        source_type="local_micro_resistance", price=micro_resistance,
        entry=proposed_entry, as_of=observation_ts_ms,
        available=micro_resistance is not None,
    ))
    swing_values = _causal_swing_highs(prior_bars)
    if swing_values:
        for value in swing_values:
            candidates.append(_candidate(
                source_type="swing_high", price=value, entry=proposed_entry,
                as_of=observation_ts_ms, available=True,
            ))
    else:
        candidates.append(_candidate(
            source_type="swing_high", price=None, entry=proposed_entry,
            as_of=observation_ts_ms, available=False,
        ))
    nearest = (context.get("structural_levels") or {}).get("nearest_resistance") or {}
    wrapped = nearest.get("value") if isinstance(nearest.get("value"), Mapping) else nearest
    nearest_price = _number_or_none(wrapped.get("price")) if isinstance(wrapped, Mapping) else None
    nearest_source = str(wrapped.get("source") or "selected_nearest_overhead_resistance") if isinstance(wrapped, Mapping) else "selected_nearest_overhead_resistance"
    selected = _candidate(
        source_type=nearest_source, price=nearest_price, entry=proposed_entry,
        as_of=observation_ts_ms, available=nearest_price is not None,
        role="selected_nearest_overhead_resistance",
    )
    if isinstance(wrapped, Mapping) and _number_or_none(wrapped.get("distance_pct")) is not None:
        selected["distance_from_entry_pct"] = float(wrapped["distance_pct"])
    candidates.append(selected)
    candidates.append(_candidate(
        source_type="detector_structural_resistance", price=None,
        entry=proposed_entry, as_of=observation_ts_ms, available=False,
    ))
    return _finalize_registry(candidates, proposed_entry, observation_ts_ms)


def _candidate(*, source_type, price, entry, as_of, available, role="candidate"):
    return {
        "source_type": source_type,
        "price": price,
        "availability": "available" if available else "unavailable",
        "as_of_ts_ms": int(as_of),
        "distance_from_entry_pct": (
            ((float(price) / float(entry)) - 1.0) * 100.0
            if available and price is not None and entry not in (None, 0) else None
        ),
        "above_proposed_entry": (
            bool(float(price) > float(entry))
            if available and price is not None and entry is not None else None
        ),
        "role": role,
    }


def _finalize_registry(candidates, entry, as_of):
    required = {
        "PMH", "ORH", "regular_session_high", "VWAP", "prior_day_high",
        "local_micro_resistance", "swing_high", "detector_structural_resistance",
    }
    evaluated = {str(item.get("source_type") or "").split(":", 1)[0] for item in candidates}
    available_required = {
        str(item.get("source_type") or "").split(":", 1)[0]
        for item in candidates if item.get("availability") == "available"
    }
    overhead = [
        item for item in candidates
        if item.get("availability") == "available"
        and item.get("above_proposed_entry") is True
        and item.get("role") != "broken_level"
    ]
    selected = min(overhead, key=lambda item: (float(item["price"]), str(item["source_type"]))) if overhead else None
    return {
        "schema_version": 1,
        "proposed_entry": entry,
        "as_of_ts_ms": int(as_of),
        "candidates": candidates,
        "selected_nearest_overhead_resistance": dict(selected) if selected else None,
        "required_sources_evaluated": sorted(required & evaluated),
        "required_sources_unavailable": sorted(required - available_required),
        "complete": required <= evaluated and required <= available_required,
        "completeness_rule": "all required sources were evaluated and have causal data",
    }


def _causal_swing_highs(bars):
    highs = [_number_or_none(item.get("high")) for item in bars[-20:]]
    return sorted({
        float(value) for index, value in enumerate(highs)
        if value is not None and index > 0 and index < len(highs) - 1
        and highs[index - 1] is not None and highs[index + 1] is not None
        and value >= highs[index - 1] and value >= highs[index + 1]
    })


def _evidence_number(raw):
    if not isinstance(raw, Mapping) or not raw.get("available"):
        return None
    value = raw.get("value")
    return _number_or_none(value)


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


def _distance_pct(price: int | float | None, level: int | float | None) -> float | None:
    if price is None or level is None or level == 0:
        return None
    return (price - level) / level * 100.0
