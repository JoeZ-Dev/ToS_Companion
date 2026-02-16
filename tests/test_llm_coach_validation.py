from momentum_companion.llm.coach import LLMCoach


def test_llm_coach_reason_codes_validation():
    coach = LLMCoach()
    assert coach.validate_response({"reason_codes": ["DATA_STALE"]})
    assert coach.validate_response({"reason_codes": ["RISK_BREACH"]})
    assert coach.validate_response({"reason_codes": []})
    assert coach.validate_response({"reason_codes": ["FAILED_BREAKOUT"]})
