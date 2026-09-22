from momentum_companion.setup_engine.pattern_contracts import PatternState, PatternType
from momentum_companion.setup_engine.pattern_engine import PatternEngine
from momentum_companion.setup_engine.patterns.ascending_triangle import detect_ascending_triangle
from momentum_companion.setup_engine.patterns.micro_pullback import detect_micro_pullback


def bar(t, o, h, l, c, v=1000):
    return {
        "time": t,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
    }


def triangle_bars(last_close=9.96):
    return [
        bar(0, 9.50, 9.80, 9.40, 9.70),
        bar(10, 9.70, 10.00, 9.70, 9.92),
        bar(20, 9.90, 9.95, 9.50, 9.70),
        bar(30, 9.72, 10.01, 9.72, 9.95),
        bar(40, 9.90, 9.95, 9.65, 9.78),
        bar(50, 9.80, 10.00, 9.80, 9.96),
        bar(60, 9.92, 9.97, 9.78, 9.88),
        bar(70, 9.90, 10.00, 9.88, last_close),
    ]


def micro_pullback_bars(last_close=10.50):
    return [
        bar(0, 10.00, 10.05, 10.00, 10.03),
        bar(10, 10.03, 10.22, 10.02, 10.20),
        bar(20, 10.20, 10.42, 10.18, 10.40),
        bar(30, 10.40, 10.60, 10.37, 10.56),
        bar(40, 10.55, 10.56, 10.47, 10.49),
        bar(50, 10.49, 10.52, 10.43, last_close),
    ]


def test_detects_ascending_triangle_with_explainable_geometry():
    observation = detect_ascending_triangle("abcd", triangle_bars())

    assert observation is not None
    assert observation.pattern_type == PatternType.ASCENDING_TRIANGLE
    assert observation.evidence["resistance_touches"] >= 2
    assert observation.evidence["higher_lows"] >= 2
    assert observation.evidence["support_slope_per_sec"] > 0
    assert {line.role for line in observation.lines} == {"resistance", "rising_support"}
    assert any(point.role == "resistance_touch" for point in observation.points)
    assert any(point.role == "higher_low" for point in observation.points)


def test_triangle_breakout_is_a_state_not_a_separate_detector():
    observation = detect_ascending_triangle("ABCD", triangle_bars(last_close=10.05))

    assert observation is not None
    assert observation.state == PatternState.BREAKOUT


def test_detects_micro_pullback_and_exposes_impulse_pullback_geometry():
    observation = detect_micro_pullback("abcd", micro_pullback_bars())

    assert observation is not None
    assert observation.pattern_type == PatternType.MICRO_PULLBACK
    assert 0.08 <= observation.evidence["retracement_pct"] <= 0.50
    assert observation.evidence["duration_sec"] <= 180
    assert {line.role for line in observation.lines} == {"impulse", "pullback"}
    assert any(point.role == "pullback_low" for point in observation.points)


def test_micro_pullback_can_transition_to_continuation():
    observation = detect_micro_pullback("ABCD", micro_pullback_bars(last_close=10.63))

    assert observation is not None
    assert observation.state == PatternState.CONTINUATION


def test_pattern_engine_returns_serializable_observations_without_external_dependencies():
    observations = PatternEngine().detect_dicts("abcd", triangle_bars())

    assert observations
    assert all(item["symbol"] == "ABCD" for item in observations)
    triangle = next(item for item in observations if item["pattern_type"] == "ASCENDING_TRIANGLE")
    assert triangle["id"].startswith("ABCD:ASCENDING_TRIANGLE:")
    assert triangle["lines"]
    assert triangle["evidence"]["resistance_touches"] >= 2


def test_detectors_return_none_for_flat_noise():
    bars = [
        bar(i * 10, 10.00, 10.02, 9.98, 10.00)
        for i in range(12)
    ]

    assert detect_ascending_triangle("FLAT", bars) is None
    assert detect_micro_pullback("FLAT", bars) is None
