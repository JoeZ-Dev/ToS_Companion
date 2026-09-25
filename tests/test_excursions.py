from momentum_companion.evaluation.excursions import compute_excursions


def test_long_mae_mfe():
    bars = [
        {"ts": 100, "high": 5.10, "low": 4.90},
        {"ts": 110, "high": 5.60, "low": 4.80},
        {"ts": 120, "high": 6.00, "low": 5.40},
    ]

    result = compute_excursions(
        bars,
        entry_ts=100,
        entry_price=5.00,
        exit_ts=120,
        side="long",
    )

    assert result is not None
    assert round(result.mae_pct, 4) == -4.0
    assert round(result.mfe_pct, 4) == 20.0
    assert result.mae_price == 4.8
    assert result.mfe_price == 6.0


def test_short_mae_mfe():
    bars = [
        {"ts": 100, "high": 10.50, "low": 9.50},
        {"ts": 110, "high": 11.00, "low": 8.00},
    ]

    result = compute_excursions(
        bars,
        entry_ts=100,
        entry_price=10.00,
        side="short",
    )

    assert result is not None
    assert round(result.mae_pct, 4) == -10.0
    assert round(result.mfe_pct, 4) == 20.0
