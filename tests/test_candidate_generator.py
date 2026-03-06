from momentum_companion.setup_engine.candidate_generator import generate_candidate_setups


def _base_payload():
    return {
        "quote": {"last": 1.0, "bid": 0.99, "ask": 1.01, "volume": 1000},
        "micro": {},
        "session": {},
        "levels": {},
        "bars_window": [],
        "derived": {},
        "structure_context": {},
        "volume_structure": {},
    }


def test_chooses_nearest_resistance():
    p = _base_payload()
    p["levels"] = {"nearest_resistance": {"price": 1.05, "source": "nearest_resistance"}}
    p["micro"] = {"micro_resistance_15m": 1.08}
    setups = generate_candidate_setups(p)
    assert setups
    assert setups[0]["entry_trigger_price"] == 1.05
    assert setups[0]["target1_label"] == "micro_resistance_15m"


def test_micro_when_no_nearest_resistance():
    p = _base_payload()
    p["micro"] = {"micro_resistance_15m": 1.08, "micro_support_15m": 0.98}
    p["session"] = {"opening_range_high": 1.12}
    setups = generate_candidate_setups(p)
    assert setups and setups[0]["name"].startswith("MICRO")


def test_tight_resistance_returns_empty_if_not_breakout():
    p = _base_payload()
    p["structure_context"] = {"next_resistance_distance_pct": 0.3}
    p["levels"] = {}
    setups = generate_candidate_setups(p)
    assert setups == []


def test_filters_move_pct_below_threshold():
    p = _base_payload()
    p["levels"] = {"nearest_resistance": {"price": 1.005, "source": "nearest_resistance"}}
    setups = generate_candidate_setups(p)
    # move pct would be below 1.5%, expect none
    assert setups == []


def test_candidate_skipped_without_structural_target():
    p = _base_payload()
    p["levels"] = {"nearest_resistance": {"price": 1.02, "source": "nearest_resistance"}}
    p["micro"] = {"micro_resistance_15m": 1.02}
    setups = generate_candidate_setups(p)
    assert setups == []


def test_candidate_uses_structural_target_above_entry():
    p = _base_payload()
    p["levels"] = {"nearest_resistance": {"price": 1.05, "source": "nearest_resistance"}}
    p["session"] = {"premarket_high": 1.12}
    setups = generate_candidate_setups(p)
    assert setups
    assert setups[0]["target_price"] == 1.12
    assert setups[0]["target1_label"] == "premarket_high"
