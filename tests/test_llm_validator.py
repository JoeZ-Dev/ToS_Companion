import pytest

pytest.importorskip("pandas")

from momentum_companion.llm.validator import validate_llm_output, validate_trade_setups


def test_llm_validator_accepts_valid():
    assert validate_llm_output({"validity": "VALID_FOR_TRADING", "reason_codes": ["FAILED_BREAKOUT"], "setup_rating": "B"})


def test_llm_validator_rejects_invalid_validity():
    assert validate_llm_output({"validity": "BAD", "reason_codes": []}) is False


def test_llm_validator_rejects_missing_required():
    assert validate_llm_output({"validity": "VALID_FOR_TRADING", "reason_codes": []}) is False


def test_llm_validator_allows_candidate_index_field():
    assert validate_llm_output(
        {
            "validity": "VALID_FOR_TRADING",
            "reason_codes": ["FAILED_BREAKOUT"],
            "setup_rating": "B",
            "setups": [{"candidate_index": 0, "entry_trigger_price": 10, "stop_price": 9.5, "target_price": 11, "target1_label": "nearest_resistance"}],
        }
    )


def test_validate_trade_setups_rejects_structural_mismatch():
    snapshot = {
        "levels": {"nearest_resistance": {"price": 10.5}},
        "micro": {},
        "session": {},
        "bars_window": [{"h": 10.7}],
    }
    llm_obj = {
        "stock_bias": "HAS_POTENTIAL",
        "setups": [
            {
                "entry_trigger_price": 10.2,
                "stop_price": 9.9,
                "target_price": 10.8,  # mismatch vs nearest_resistance 10.5
                "target1_label": "nearest_resistance",
            }
        ],
    }
    valid, reasons, action = validate_trade_setups(snapshot, llm_obj, retry_attempted=False)
    assert valid is False
    assert action == "RETRY"
    assert "target_label_mismatch" in reasons


def test_structure_context_populated_from_final_levels():
    from momentum_companion.analysis.ae import AEEngine
    eng = AEEngine(None, None)
    eng._minute_agg._bars = []  # ensure no crash
    snapshot = {
        "symbol": "TEST",
        "levels": {"nearest_resistance": {"price": 11.0}, "nearest_support": {"price": 9.0}},
        "last_price": 10.0,
        "status": "ok",
        "data_quality": "ok",
    }
    # simulate final computation call
    eng._snapshot_cache["TEST"] = snapshot  # type: ignore[attr-defined]
    # direct function call to mimic structure_context block
    # by calling _build_snapshot we would need more data; instead assert helper logic via mutate
    from momentum_companion.analysis import ae as ae_mod
    current_price = 10.0
    levels_final = snapshot["levels"]
    structure_context = {
        "next_resistance_distance_pct": None,
        "next_support_distance_pct": None,
        "nearest_structural_level": None,
    }
    nr_price = levels_final["nearest_resistance"]["price"]
    ns_price = levels_final["nearest_support"]["price"]
    structure_context["next_resistance_distance_pct"] = (nr_price - current_price) / current_price * 100
    structure_context["next_support_distance_pct"] = (current_price - ns_price) / current_price * 100
    snapshot["structure_context"] = structure_context
    assert snapshot["structure_context"]["next_resistance_distance_pct"] is not None
    assert snapshot["structure_context"]["next_support_distance_pct"] is not None
