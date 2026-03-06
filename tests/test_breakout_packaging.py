import pytest

pytest.importorskip("pandas")

from momentum_companion.analysis.ae import pick_nearest_resistance
from momentum_companion.llm.normalization import _compute_breakout_targets


def test_nearest_resistance_skips_trivial_above_price():
    current_price = 6.65
    micro = {}
    session = {}
    bars = [{"h": 6.6}, {"h": 6.62}, {"h": 6.67}, {"h": 7.2}]
    existing = {"price": 6.6, "source": "nearest_resistance"}
    nr = pick_nearest_resistance(current_price, micro, session, bars, existing)
    assert nr is not None
    assert nr["price"] == 7.2  # skips <=0.2% above price


def test_breakout_targets_skip_noise_and_use_higher_structures():
    snapshot = {
        "levels": {"nearest_resistance": {"price": 6.6}},
        "session": {"premarket_high": 7.5},
        "bars_window": [{"h": 6.6}, {"h": 6.62}, {"h": 6.67}, {"h": 7.4}],
        "quote": {"last": 6.65},
    }
    out = _compute_breakout_targets(snapshot)
    # nearest_breakout_trigger should be dropped because trigger is already at/through price
    assert "nearest_breakout_trigger" not in out or out["nearest_breakout_trigger"] > 6.65 * 1.002
    # if trigger were valid, next_structural_target_above_trigger should skip noise and choose 7.4


def test_breakout_targets_when_trigger_above_price():
    snapshot = {
        "levels": {"nearest_resistance": {"price": 6.96}},
        "session": {"premarket_high": 7.4},
        "bars_window": [{"h": 6.96}, {"h": 7.4}],
        "quote": {"last": 6.6},
    }
    out = _compute_breakout_targets(snapshot)
    assert out["nearest_breakout_trigger"] == 6.96
    assert out["next_structural_target_above_trigger"] == 7.4
