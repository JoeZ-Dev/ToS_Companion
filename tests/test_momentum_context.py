from momentum_companion.analysis.excursions import measure_long_excursion
from momentum_companion.setup_engine.confirmation import evaluate_price_confirmation


def bar(t, close, low=None, high=None):
    return {
        "time": t,
        "open": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
        "volume": 100,
    }


def test_confirmation_adapts_to_fast_and_slow_formations():
    fast = [bar(100, 10.1), bar(110, 10.2)]
    slow = [bar(1000, 10.1), bar(1010, 10.2)]

    fast_result = evaluate_price_confirmation(
        fast,
        trigger_price=10.0,
        pattern_started_at=90,
        min_seconds=3,
        max_seconds=30,
        formation_fraction=0.05,
    )
    slow_result = evaluate_price_confirmation(
        slow,
        trigger_price=10.0,
        pattern_started_at=400,
        min_seconds=3,
        max_seconds=30,
        formation_fraction=0.05,
    )

    assert fast_result.required_seconds == 3
    assert slow_result.required_seconds == 30
    assert fast_result.confirmed is True
    assert slow_result.confirmed is False


def test_confirmation_does_not_bridge_real_data_gap():
    result = evaluate_price_confirmation(
        [bar(0, 10.1), bar(10, 10.2), bar(100, 10.3)],
        trigger_price=10.0,
        pattern_started_at=-100,
        min_seconds=5,
        max_seconds=30,
        formation_fraction=0.05,
        max_gap_seconds=30,
    )

    assert result.gap_broken is True
    assert result.streak_started_at == 100
    assert result.elapsed_seconds == 10
    assert result.confirmed is True


def test_long_excursion_reports_mae_and_mfe():
    result = measure_long_excursion(
        [
            bar(0, 10.0, low=9.9, high=10.1),
            bar(10, 10.2, low=9.6, high=10.8),
            bar(20, 10.5, low=10.0, high=11.2),
        ],
        entry_price=10.0,
        entry_ts=0,
    )

    assert result is not None
    assert round(result.mae_pct, 2) == -4.0
    assert round(result.mfe_pct, 2) == 12.0
    assert result.mae_ts == 10
    assert result.mfe_ts == 20
