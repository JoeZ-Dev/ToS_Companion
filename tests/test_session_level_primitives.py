from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from momentum_companion.setup_engine.structure.session_levels import (
    SessionLevelConfig,
    session_level_context,
)


ET = ZoneInfo("America/New_York")


def bar(day, clock, *, high, low, close=None, volume=100):
    timestamp = int(datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=ET).timestamp())
    close = close if close is not None else (high + low) / 2
    return {
        "time": timestamp,
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def test_session_boundaries_keep_premarket_and_regular_extremes_separate():
    bars = [
        bar("2026-09-25", "04:00:00", high=8.0, low=7.0),
        bar("2026-09-25", "09:29:00", high=12.0, low=6.0),
        bar("2026-09-25", "09:30:00", high=10.0, low=8.0),
        bar("2026-09-25", "09:39:00", high=11.0, low=7.5),
        bar("2026-09-25", "09:45:00", high=13.0, low=7.0),
    ]
    as_of = int(datetime(2026, 9, 25, 9, 46, tzinfo=ET).timestamp())

    context = session_level_context(bars, as_of_ts=as_of, current_price=12.0, vwap=9.0)

    assert context["levels"]["premarket_high"] == 12.0
    assert context["levels"]["premarket_low"] == 6.0
    assert context["levels"]["regular_session_high"] == 13.0
    assert context["levels"]["regular_session_low"] == 7.0
    assert context["levels"]["opening_range_high"] == 11.0
    assert context["levels"]["opening_range_low"] == 7.5
    assert context["opening_range_complete"] is True
    assert context["distances_pct"]["vwap"] == pytest.approx(33.333333)


def test_opening_range_duration_is_explicit_configuration():
    bars = [
        bar("2026-09-25", "09:30:00", high=10.0, low=9.0),
        bar("2026-09-25", "09:36:00", high=12.0, low=8.0),
    ]
    as_of = int(datetime(2026, 9, 25, 9, 41, tzinfo=ET).timestamp())

    five = session_level_context(
        bars,
        as_of_ts=as_of,
        config=SessionLevelConfig(opening_range_minutes=5),
    )
    ten = session_level_context(
        bars,
        as_of_ts=as_of,
        config=SessionLevelConfig(opening_range_minutes=10),
    )

    assert five["levels"]["opening_range_high"] == 10.0
    assert ten["levels"]["opening_range_high"] == 12.0
    assert five["opening_range_minutes"] == 5
    assert ten["opening_range_minutes"] == 10


def test_prior_day_levels_use_latest_available_regular_session_only():
    bars = [
        bar("2026-09-23", "15:59:00", high=3.0, low=2.0, close=2.5),
        bar("2026-09-24", "08:00:00", high=20.0, low=1.0, close=10.0),
        bar("2026-09-24", "09:30:00", high=5.0, low=4.0, close=4.5),
        bar("2026-09-24", "15:59:00", high=7.0, low=3.0, close=6.5),
        bar("2026-09-25", "09:30:00", high=8.0, low=6.0),
    ]
    as_of = int(datetime(2026, 9, 25, 9, 31, tzinfo=ET).timestamp())

    levels = session_level_context(bars, as_of_ts=as_of)["levels"]

    assert levels["prior_day_high"] == 7.0
    assert levels["prior_day_low"] == 3.0
    assert levels["prior_day_close"] == 6.5


def test_vwap_falls_back_to_supplied_bar_evidence_and_missing_stays_unavailable():
    bars = [bar("2026-09-25", "09:30:00", high=12.0, low=9.0, close=9.0, volume=100)]
    as_of = int(datetime(2026, 9, 25, 9, 31, tzinfo=ET).timestamp())

    context = session_level_context(bars, as_of_ts=as_of)
    empty = session_level_context([], as_of_ts=as_of, current_price=10.0)

    assert context["levels"]["vwap"] == 10.0
    assert context["vwap_source"] == "calculated_from_bars"
    assert empty["levels"]["prior_day_close"] is None
    assert empty["distances_pct"]["prior_day_close"] is None


def test_future_bars_are_not_visible_at_as_of_time():
    bars = [
        bar("2026-09-25", "09:30:00", high=10.0, low=9.0),
        bar("2026-09-25", "09:35:00", high=99.0, low=1.0),
    ]
    as_of = int(datetime(2026, 9, 25, 9, 31, tzinfo=ET).timestamp())

    levels = session_level_context(bars, as_of_ts=as_of)["levels"]

    assert levels["regular_session_high"] == 10.0
    assert levels["regular_session_low"] == 9.0
