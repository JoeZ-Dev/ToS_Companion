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


class StaticClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def complete(self, _msgs, model_override=None):
        if self._responses:
            return self._responses.pop(0)
        return {}


class CandidateCoach(LLMCoach):
    def validate_response(self, resp):
        return True


def test_llm_service_candidate_mismatch_triggers_mismatch_reason():
    payload_snapshot = {
        "status": "ok",
        "data_quality": "ok",
        "as_of_ts_ms": 1,
        "symbol": "ABC",
        "market_state": "normal",
        "quote": {"bid": 10, "ask": 10.1, "last": 10.05},
        "bars_window_5m": [{"ts_ms": 1, "o": 10, "h": 10, "l": 10, "c": 10, "v": 100}] * 25,
        "levels": {"nearest_resistance": {"price": 10.5, "source": "nearest_resistance"}, "nearest_support": {"price": 9.5, "source": "nearest_support"}},
        "session": {"premarket_high": 10.4, "premarket_low": 9.8, "opening_range_high": 10.3, "opening_range_low": 9.9},
        "candidate_setups": [
            {"entry_trigger_price": 10.5, "stop_price": 10.3, "target_price": 10.9, "target1_label": "nearest_resistance"},
        ],
    }
    # Both initial and repair responses mismatch target_price to force candidate mismatch after retry.
    bad_resp = {
        "validity": "VALID_FOR_TRADING",
        "reason_codes": ["FAILED_BREAKOUT"],
        "setup_rating": "B",
        "setups": [
            {
                "candidate_index": 0,
                "entry_trigger_price": 10.5,
                "stop_price": 10.3,
                "target_price": 11.0,  # mismatch vs candidate 10.9
                "target1_label": "nearest_resistance",
            }
        ],
    }
    client = StaticClient([bad_resp, bad_resp])
    svc = LLMService(CandidateCoach(), client=client)
    rec = svc.evaluate(payload_snapshot, "SEAMLESS", {"bid": 10, "ask": 10.1, "last": 10.05, "volume": 100}, messages_override=[{"role": "user", "content": "x"}])
    assert rec["validity"] == "NOT_VALID_FOR_TRADING"
    assert rec.get("reason_codes") == ["LLM_CANDIDATE_MISMATCH"]


def test_llm_service_mock_client():
    client = LLMClient(api_key="x", model="gpt-mock", mode="mock")
    svc = LLMService(DummyCoach(), client=client)
    resp = svc.evaluate(
        {"status": "ok", "data_quality": "ok", "as_of_ts_ms": 1, "symbol": "AAPL", "market_state": "normal"},
        "SEAMLESS",
        {"bid": 1, "ask": 2, "last": 1.5, "volume": 100},
    )
    assert resp["validity"] == "VALID_FOR_TRADING"
