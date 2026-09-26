from momentum_companion.setup_engine.confirmation import (
    AdaptiveConfirmationPolicy,
    measure_confirmation,
)


def _bar(ts, close):
    return {
        "ts": ts,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100,
    }


def test_confirmation_target_adapts_to_formation_duration():
    policy = AdaptiveConfirmationPolicy(
        min_seconds=5,
        max_seconds=30,
        formation_fraction=0.10,
    )

    fast = policy.target_seconds(60)
    slow = policy.target_seconds(600)

    assert fast == 6
    assert slow == 30


def test_confirmation_uses_real_elapsed_time_and_resets_across_large_gap():
    bars = [
        _bar(100, 11),
        _bar(110, 11),
        _bar(120, 11),
        _bar(300, 11),
        _bar(310, 11),
    ]
    result = measure_confirmation(
        bars,
        qualifies=lambda bar: bar.close >= 10,
        formation_started_at=100,
        policy=AdaptiveConfirmationPolicy(
            min_seconds=20,
            max_seconds=20,
            formation_fraction=0,
        ),
    )

    assert result.acceptance_seconds == 20
    assert result.confirmed is True
    assert result.started_at == 300


def test_confirmation_only_counts_current_trailing_acceptance():
    bars = [
        _bar(100, 11),
        _bar(110, 11),
        _bar(120, 9),
        _bar(130, 11),
    ]
    result = measure_confirmation(
        bars,
        qualifies=lambda bar: bar.close >= 10,
        formation_started_at=100,
        policy=AdaptiveConfirmationPolicy(
            min_seconds=20,
            max_seconds=20,
            formation_fraction=0,
        ),
    )

    assert result.acceptance_seconds == 10
    assert result.confirmed is False
    assert result.started_at == 130
