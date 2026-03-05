from momentum_companion.analysis.ae import pick_nearest_resistance


def test_picks_micro_resistance_first():
    current = 1.0
    micro = {"micro_resistance_15m": 1.05}
    session = {"opening_range_high": 1.1, "premarket_high": 1.2}
    bars = []
    out = pick_nearest_resistance(current, micro, session, bars, None)
    assert out["source"] == "micro_resistance_15m"
    assert out["price"] == 1.05


def test_falls_back_to_orh():
    current = 1.0
    micro = {"micro_resistance_15m": None}
    session = {"opening_range_high": 1.08, "premarket_high": 1.2}
    bars = []
    out = pick_nearest_resistance(current, micro, session, bars, None)
    assert out["source"] == "opening_range_high"
    assert out["price"] == 1.08


def test_falls_back_to_pmh():
    current = 1.0
    micro = {"micro_resistance_15m": None}
    session = {"opening_range_high": None, "premarket_high": 1.15}
    bars = []
    out = pick_nearest_resistance(current, micro, session, bars, None)
    assert out["source"] == "premarket_high"
    assert out["price"] == 1.15


def test_uses_swing_high():
    current = 1.0
    micro = {"micro_resistance_15m": None}
    session = {"opening_range_high": None, "premarket_high": None}
    bars = [{"h": 1.02}, {"h": 1.06}, {"h": 0.99}, {"h": 1.04}]
    out = pick_nearest_resistance(current, micro, session, bars, None)
    assert out["source"] == "swing_high"
    assert out["price"] == 1.02


def test_returns_none_when_no_level_above_price():
    current = 1.0
    micro = {"micro_resistance_15m": 0.9}
    session = {"opening_range_high": 0.95, "premarket_high": 0.97}
    bars = [{"h": 0.99}, {"h": 0.5}]
    out = pick_nearest_resistance(current, micro, session, bars, None)
    assert out is None
