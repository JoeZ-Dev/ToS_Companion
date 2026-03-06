from momentum_companion.llm.service import LLMService
from momentum_companion.llm.coach import LLMCoach


class DummyCoach(LLMCoach):
    def __init__(self, resp):
        super().__init__()
        self._resp = resp

    def run(self, snapshot_payload, context):
        return self._resp

    def validate_response(self, resp):
        return True


def _base_snapshot():
    return {
        "status": "ok",
        "data_quality": "partial",
        "as_of_ts_ms": 1,
        "symbol": "ABC",
        "market_state": "normal",
        "quote": {"bid": 10, "ask": 10.1, "last": 10.05},
        "bars_window_5m": [{"ts_ms": 1, "o": 10, "h": 10, "l": 10, "c": 10, "v": 100}] * 25,
        "levels": {"nearest_resistance": {"price": 11.0, "source": "nearest_resistance"}},
        "session": {"premarket_high": 10.9},
    }


def test_missing_setups_repaired_to_empty():
    coach = DummyCoach({"stock_bias": "NO_EDGE", "summary": "Test"})  # missing setups
    svc = LLMService(coach)
    rec = svc.evaluate(_base_snapshot(), "SEAMLESS", {"bid": 10, "ask": 10.1, "last": 10.05, "volume": 100})
    assert rec.get("setups") == []
    assert rec.get("stock_bias") in {"NO_EDGE", "HAS_POTENTIAL"}


def test_watch_output_survives():
    watch_resp = {
        "stock_bias": "HAS_POTENTIAL",
        "summary": "Breakout watch.",
        "setups": [
            {
                "name": "BREAK",
                "setup_state": "WATCH",
                "trigger_condition": "1m close above 11.0 AND hold/retest",
                "entry_trigger_price": 11.0,
                "stop_price": 10.7,
                "target_price": 12.0,
                "rr_to_target1": (12.0 - 11.0) / (11.0 - 10.7),
                "move_pct_to_target1": (12.0 - 11.0) / 11.0,
                "setup_rating": "B",
                "confirmation_requirements": "hold",
                "target1_label": "swing_high",
                "extension_trigger": "",
                "extension_target": None,
                "extension_notes": "",
                "tape_warning": "NONE",
            }
        ],
    }
    coach = DummyCoach(watch_resp)
    svc = LLMService(coach)
    snap = _base_snapshot()
    snap["bars_window_5m"][0]["h"] = 12.0  # ensure swing high matches target
    rec = svc.evaluate(snap, "SEAMLESS", {"bid": 10, "ask": 10.1, "last": 10.05, "volume": 100})
    assert rec.get("stock_bias") == "HAS_POTENTIAL"
    assert rec.get("setups")


def test_ready_with_bad_rr_still_fails():
    ready_resp = {
        "stock_bias": "HAS_POTENTIAL",
        "summary": "Bad RR.",
        "setups": [
            {
                "name": "BAD",
                "setup_state": "READY",
                "trigger_condition": "now",
                "entry_trigger_price": 10.0,
                "stop_price": 9.9,
                "target_price": 10.01,
                "rr_to_target1": (10.01 - 10.0) / (10.0 - 9.9),
                "move_pct_to_target1": (10.01 - 10.0) / 10.0,
                "setup_rating": "B",
                "confirmation_requirements": "none",
                "target1_label": "nearest_resistance",
                "extension_trigger": "",
                "extension_target": None,
                "extension_notes": "",
                "tape_warning": "NONE",
            }
        ],
    }
    coach = DummyCoach(ready_resp)
    svc = LLMService(coach)
    rec = svc.evaluate(_base_snapshot(), "SEAMLESS", {"bid": 10, "ask": 10.1, "last": 10.05, "volume": 100})
    assert rec.get("validity") == "NOT_VALID_FOR_TRADING"
    assert rec.get("stock_bias") == "NO_EDGE"
    assert rec.get("setups") == []
