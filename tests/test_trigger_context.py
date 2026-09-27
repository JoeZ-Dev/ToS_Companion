from datetime import datetime
from zoneinfo import ZoneInfo

from momentum_companion.recording.trigger_context import build_trigger_context


def test_context_distinguishes_false_zero_and_unavailable_values():
    timestamp_ms = int(
        datetime(2026, 9, 28, 9, 35, tzinfo=ZoneInfo("America/New_York")).timestamp()
        * 1000
    )
    context = build_trigger_context(
        symbol_state={
            "quote": {
                "ts_ms": timestamp_ms,
                "last": 4.25,
                "volume": 0,
                "security_status": "Normal",
                "halted": False,
                "hard_to_borrow": False,
                "hard_to_borrow_quantity": 0,
                "hard_to_borrow_rate": None,
                "shortable": True,
                "net_percentage_change": 18.5,
            },
            "market_context": {
                "relative_strength_rank": 1,
                "relative_strength_universe_size": 4,
            },
            "ae_snapshot": {
                "vwap": 4.0,
                "derived": {"distance_to_vwap_pct": 0.0625},
                "volume": {"volume_multiple": None},
                "fundamentals": {"shares_outstanding": None},
                "session": {"premarket_high": 4.5, "premarket_low": 3.1},
                "levels": {},
            },
        },
        bar={"close": 4.25, "volume": 0},
        observation_ts_ms=timestamp_ms - 10_000,
    )

    assert context["session_phase"]["value"] == "RTH"
    assert context["security"]["halted"] == {
        "available": True,
        "value": False,
        "source": "normalized_quote.explicit_security_status",
    }
    assert context["borrow"]["quantity"]["available"] is True
    assert context["borrow"]["quantity"]["value"] == 0
    assert context["borrow"]["rate"]["available"] is False
    assert context["fundamentals"]["shares_outstanding"]["available"] is False
    assert context["volume"]["completed_bar"]["value"] == 0
    assert context["context_as_of_ts_ms"] == timestamp_ms


def test_context_falls_back_to_completed_bar_close_without_quote_price():
    context = build_trigger_context(
        symbol_state={"quote": {}, "market_context": {}, "ae_snapshot": {}},
        bar={"close": 3.2, "volume": 100},
        observation_ts_ms=1_800_000_000_000,
    )

    assert context["price"]["value"] == 3.2
    assert context["price"]["source"] == "completed_bar.close"
    assert context["vwap"]["available"] is False
    assert context["security"]["halted"]["available"] is False
