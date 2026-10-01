import pytest

from momentum_companion.setup_engine.structure.volume import (
    current_volume_expansion,
    recent_volume_stats,
    volume_ratio,
    volume_trend,
)


def bars(*volumes):
    return [{"volume": value} for value in volumes]


def test_recent_volume_stats_use_completed_lookback():
    stats = recent_volume_stats(bars(1, 2, 3, 100), lookback=3)

    assert stats == {
        "lookback": 3,
        "observations": 3,
        "mean": 35,
        "median": 3,
    }


def test_generic_contraction_and_expansion_ratios():
    assert volume_ratio(bars(25, 25), bars(100, 100)) == 0.25
    assert current_volume_expansion({"volume": 300}, bars(100, 100), lookback=2) == 3
    assert volume_ratio(bars(25), bars(0, 0)) is None
    assert current_volume_expansion({"volume": 0}, bars(100, 100)) == 0


def test_volume_trend_reports_slope_and_direction():
    rising = volume_trend(bars(100, 200, 300), lookback=3)
    falling = volume_trend(bars(300, 200, 100), lookback=3)

    assert rising["slope_per_bar"] == pytest.approx(100)
    assert rising["direction"] == "rising"
    assert falling["direction"] == "falling"
    assert volume_trend(bars(100), lookback=3)["direction"] is None


def test_invalid_volume_values_are_unavailable_instead_of_zero():
    stats = recent_volume_stats([{"volume": None}, {"volume": "bad"}], lookback=2)

    assert stats["observations"] == 0
    assert stats["mean"] is None
    with pytest.raises(ValueError):
        recent_volume_stats([], lookback=0)
