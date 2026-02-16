from momentum_companion.llm.service import LLMService
from momentum_companion.llm.coach import LLMCoach
from momentum_companion.llm.client import LLMClient


class DummyCoach(LLMCoach):
    def run(self, snapshot_payload, context):
        return {"validity": "VALID_FOR_TRADING", "reason_codes": ["FAILED_BREAKOUT"], "setup_rating": "B"}

    def validate_response(self, resp):
        return True


def test_llm_service_validate_passes_allowed_reason_codes():
    svc = LLMService(DummyCoach())
    resp = svc.evaluate(
        {"status": "ok", "data_quality": "ok", "as_of_ts_ms": 1, "symbol": "AAPL", "market_state": "normal"},
        "SEAMLESS",
        {"bid": 1, "ask": 2, "last": 1.5, "volume": 100},
    )
    assert resp["validity"] == "VALID_FOR_TRADING"


def test_llm_service_mock_client():
    client = LLMClient(api_key="x", model="gpt-mock", mode="mock")
    svc = LLMService(DummyCoach(), client=client)
    resp = svc.evaluate(
        {"status": "ok", "data_quality": "ok", "as_of_ts_ms": 1, "symbol": "AAPL", "market_state": "normal"},
        "SEAMLESS",
        {"bid": 1, "ask": 2, "last": 1.5, "volume": 100},
    )
    assert resp["validity"] == "VALID_FOR_TRADING"
