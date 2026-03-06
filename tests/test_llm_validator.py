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
