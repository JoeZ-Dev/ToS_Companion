from momentum_companion.llm.validator import validate_llm_output


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
