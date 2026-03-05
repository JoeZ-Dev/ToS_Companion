from momentum_companion.llm.validator import validate_llm_selected_candidates


def _payload():
    return {
        "candidate_setups": [
            {
                "entry_trigger_price": 10.0,
                "stop_price": 9.8,
                "target_price": 10.5,
                "target1_label": "nearest_resistance",
            },
            {
                "entry_trigger_price": 11.0,
                "stop_price": 10.7,
                "target_price": 11.7,
                "target1_label": "opening_range_high",
            },
        ]
    }


def _resp(setups):
    return {"validity": "VALID_FOR_TRADING", "reason_codes": ["FAILED_BREAKOUT"], "setup_rating": "B", "setups": setups}


def test_candidate_selection_valid_passes():
    payload = _payload()
    resp = _resp(
        [
            {
                "candidate_index": 0,
                "entry_trigger_price": 10.0,
                "stop_price": 9.8,
                "target_price": 10.5,
                "target1_label": "nearest_resistance",
            }
        ]
    )
    out, ok, reasons, action = validate_llm_selected_candidates(payload, resp, retry_attempted=False)
    assert ok is True
    assert action == "OK"
    assert out["setups"][0]["candidate_index"] == 0
    assert reasons == []


def test_candidate_selection_mismatch_triggers_retry():
    payload = _payload()
    resp = _resp(
        [
            {
                "candidate_index": 0,
                "entry_trigger_price": 10.0,
                "stop_price": 9.8,
                "target_price": 10.5,
                "target1_label": "opening_range_high",
            }
        ]
    )
    out, ok, reasons, action = validate_llm_selected_candidates(payload, resp, retry_attempted=False)
    assert ok is False
    assert action == "RETRY"
    assert "candidate_mismatch" in reasons
    assert out["setups"] == []


def test_candidate_selection_out_of_range():
    payload = _payload()
    resp = _resp(
        [
            {
                "candidate_index": 5,
                "entry_trigger_price": 10.0,
                "stop_price": 9.8,
                "target_price": 10.5,
                "target1_label": "nearest_resistance",
            }
        ]
    )
    _, ok, reasons, action = validate_llm_selected_candidates(payload, resp, retry_attempted=False)
    assert ok is False
    assert action == "RETRY"
    assert "candidate_index_out_of_range" in reasons


def test_candidate_selection_mixed_keeps_valid():
    payload = _payload()
    resp = _resp(
        [
            {
                "candidate_index": 0,
                "entry_trigger_price": 10.0,
                "stop_price": 9.8,
                "target_price": 10.5,
                "target1_label": "opening_range_high",
            },
            {
                "candidate_index": 1,
                "entry_trigger_price": 11.0,
                "stop_price": 10.7,
                "target_price": 11.7,
                "target1_label": "opening_range_high",
            },
        ]
    )
    out, ok, reasons, action = validate_llm_selected_candidates(payload, resp, retry_attempted=False)
    assert ok is True
    assert action == "OK"
    assert len(out["setups"]) == 1
    assert out["setups"][0]["candidate_index"] == 1
    assert "candidate_mismatch" in reasons


def test_candidate_selection_no_candidates_is_noop():
    payload = {}
    resp = _resp(
        [
            {
                "candidate_index": 0,
                "entry_trigger_price": 10.0,
                "stop_price": 9.8,
                "target_price": 10.5,
                "target1_label": "nearest_resistance",
            }
        ]
    )
    out, ok, reasons, action = validate_llm_selected_candidates(payload, resp, retry_attempted=False)
    assert ok is True
    assert action == "OK"
    assert out["setups"] == resp["setups"]
    assert reasons == []
