from momentum_companion.setup_engine.confirmation import (
    AdaptiveConfirmationPolicy,
    evaluate_adaptive_confirmation,
)


def bar(t, close):
    return {
        "time": t,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100,
    }


def test_adaptive_confirmation_scales_with_pattern_age_and_cadence():
    policy = AdaptiveConfirmationPolicy(
        min_seconds=5,
        max_seconds=30,
        pattern_fraction=0.10,
    )
    result = evaluate_adaptive_confirmation(
        [bar(0, 9.9), bar(10, 10.1), bar(20, 10.2)],
        level=10.0,
        direction="above",
        pattern_started_at=0,
        policy=policy,
    )

    assert result.observed_cadence_seconds == 10
    assert result.required_seconds == 10
    assert result.elapsed_seconds == 20
    assert result.confirmed is True


def test_adaptive_confirmation_resets_on_wrong_side():
    policy = AdaptiveConfirmationPolicy(5, 30, 0.10)
    result = evaluate_adaptive_confirmation(
        [bar(0, 10.1), bar(10, 9.9), bar(20, 10.2)],
        level=10.0,
        direction="above",
        pattern_started_at=0,
        policy=policy,
    )

    assert result.consecutive_bars == 1
    assert result.elapsed_seconds == 10
    assert result.confirmed is True


def test_adaptive_confirmation_does_not_bridge_large_gap_or_halt():
    policy = AdaptiveConfirmationPolicy(
        min_seconds=20,
        max_seconds=30,
        pattern_fraction=0.10,
        minimum_gap_reset_seconds=20,
    )
    result = evaluate_adaptive_confirmation(
        [bar(0, 10.1), bar(10, 10.2), bar(120, 10.3)],
        level=10.0,
        direction="above",
        pattern_started_at=0,
        policy=policy,
    )

    assert result.gap_detected is True
    assert result.consecutive_bars == 1
    assert result.elapsed_seconds == 10
    assert result.confirmed is False
