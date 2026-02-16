from momentum_companion.llm.service import LLMService
from momentum_companion.llm.coach import LLMCoach


class DummyCoach(LLMCoach):
    def run(self, payload, context):
        return {"validity": "VALID_FOR_TRADING", "setup_rating": "A", "reason_codes": ["ENTRY_APPROACHING"]}

    def validate_response(self, resp):
        return True


def test_flash_on_validity_flip():
    flashes = []
    svc = LLMService(DummyCoach(), flash_callback=lambda s, r, p: flashes.append(r))
    base = {"symbol": "AAPL", "as_of_ts_ms": 1}
    svc.evaluate(base, "SEAMLESS", {"bid": 1, "ask": 2})
    # flip validity
    class Coach2(DummyCoach):
        def run(self, payload, context):
            return {"validity": "NOT_VALID_FOR_TRADING", "setup_rating": "A", "reason_codes": ["ENTRY_APPROACHING"]}

    svc2 = LLMService(Coach2(), flash_callback=lambda s, r, p: flashes.append(r))
    svc2._last_rec_by_symbol = svc._last_rec_by_symbol  # reuse state
    svc2.evaluate(base, "SEAMLESS", {"bid": 1, "ask": 2})
    assert flashes


def test_flash_on_price_delta():
    flashes = []

    class Coach(DummyCoach):
        def __init__(self, entry):
            self.entry = entry

        def run(self, payload, context):
            return {"validity": "VALID_FOR_TRADING", "setup_rating": "A", "reason_codes": [], "entry_price": self.entry}

    svc = LLMService(Coach(10.0), flash_callback=lambda s, r, p: flashes.append(r))
    base = {"symbol": "AAPL", "as_of_ts_ms": 1}
    svc.evaluate(base, "SEAMLESS", {"bid": 1, "ask": 2})
    svc._coach = Coach(10.2)  # 2% change
    svc.evaluate(base, "SEAMLESS", {"bid": 1, "ask": 2})
    assert flashes


def test_flash_on_action_urgency_high():
    flashes = []

    class Coach(DummyCoach):
        def run(self, payload, context):
            return {
                "validity": "VALID_FOR_TRADING",
                "setup_rating": "A",
                "reason_codes": [],
                "trade_management_action": "EXIT_NOW",
                "action_urgency": "HIGH",
            }

    svc = LLMService(Coach(), flash_callback=lambda s, r, p: flashes.append(r))
    base = {"symbol": "AAPL", "as_of_ts_ms": 1}
    svc.evaluate(base, "SEAMLESS", {"bid": 1, "ask": 2})
    # second evaluation triggers comparison
    svc.evaluate(base, "SEAMLESS", {"bid": 1, "ask": 2})
    assert flashes
