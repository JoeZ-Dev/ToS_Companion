from momentum_companion.data.bar_aggregator import TenSecondBar
from momentum_companion.replay.evaluation import ReplayExcursionEvaluator


def bar(ts, low, high, close):
    return TenSecondBar(
        ts=ts,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=100,
        is_extended=False,
    )


def test_excursion_starts_after_confirmation_bar_without_lookahead():
    evaluator = ReplayExcursionEvaluator(horizon_seconds=20)
    patterns = [{
        "id": "AAA:ASCENDING_TRIANGLE:0",
        "pattern_type": "ASCENDING_TRIANGLE",
        "state": "BREAKOUT",
    }]

    evaluator.observe_patterns(patterns, bar_ts=100, close=10.0)
    first = evaluator.snapshot()["signals"][0]
    assert first["bars_observed"] == 0
    assert first["mae_pct"] is None
    assert first["mfe_pct"] is None

    evaluator.advance_bar(bar(110, 9.8, 10.5, 10.4))
    evaluator.advance_bar(bar(120, 9.9, 11.0, 10.8))
    signal = evaluator.snapshot()["signals"][0]

    assert signal["closed"] is True
    assert signal["mae_pct"] == -1.999999999999993
    assert signal["mfe_pct"] == 10.0
    assert signal["return_pct"] == 8.000000000000007


def test_excursion_opens_only_on_first_transition_to_entry_state():
    evaluator = ReplayExcursionEvaluator()
    pattern = {
        "id": "AAA:MICRO_PULLBACK:0",
        "pattern_type": "MICRO_PULLBACK",
        "state": "CONTINUATION",
    }

    evaluator.observe_patterns([pattern], bar_ts=100, close=10.0)
    evaluator.observe_patterns([pattern], bar_ts=110, close=10.2)

    assert len(evaluator.snapshot()["signals"]) == 1
