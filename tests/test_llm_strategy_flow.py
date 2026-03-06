import pytest

pytest.importorskip("PySide6")

from momentum_companion.llm.coach import LLMCoach
from momentum_companion.llm.service import LLMService


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
        "data_quality": "ok",
        "as_of_ts_ms": 1,
        "symbol": "ABC",
        "market_state": "normal",
        "quote": {"bid": 10, "ask": 10.1, "last": 10.05},
        "bars_window_5m": [{"ts_ms": i, "o": 10, "h": 10.5, "l": 9.8, "c": 10.1, "v": 100} for i in range(25)],
        "levels": {"nearest_resistance": {"price": 11.0, "source": "nearest_resistance"}},
        "session": {"premarket_high": 10.9},
    }


def _resp(trigger: str, target: float):
    return {
        "validity": "VALID_FOR_TRADING",
        "setup_rating": "B",
        "reason_codes": ["FAILED_BREAKOUT"],
        "stock_bias": "HAS_POTENTIAL",
        "setups": [
            {
                "name": "BREAKOUT_PLAN",
                "trigger_condition": trigger,
                "entry_trigger_price": 10.5,
                "stop_price": 10.0,
                "target_price": target,
                "rr_to_target1": (target - 10.5) / (10.5 - 10.0),
                "move_pct_to_target1": (target - 10.5) / 10.5,
                "setup_rating": "B",
                "confirmation_requirements": "hold/retest",
                "target1_label": "nearest_resistance",
                "extension_trigger": "",
                "extension_target": None,
                "extension_notes": "",
                "tape_warning": "NONE",
            }
        ],
    }


def test_empty_candidates_do_not_block_llm():
    svc = LLMService(DummyCoach(_resp("break over 10.5", 11.0)))
    rec = svc.evaluate(_base_snapshot(), "SEAMLESS", {"bid": 10, "ask": 10.1, "last": 10.05, "volume": 100})
    assert rec["validity"] == "VALID_FOR_TRADING"
    assert rec.get("setups")


def test_conditional_breakout_setup_allowed():
    svc = LLMService(DummyCoach(_resp("watch for break above 10.5 with volume", 11.0)))
    rec = svc.evaluate(_base_snapshot(), "SEAMLESS", {"bid": 10, "ask": 10.1, "last": 10.05, "volume": 100})
    assert rec["validity"] == "VALID_FOR_TRADING"
    assert "break above" in rec["setups"][0]["trigger_condition"]


def test_structural_mismatch_fails_validation():
    svc = LLMService(DummyCoach(_resp("break over 10.5", 12.5)))  # target not matching nearest_resistance or bars
    rec = svc.evaluate(_base_snapshot(), "SEAMLESS", {"bid": 10, "ask": 10.1, "last": 10.05, "volume": 100})
    assert rec["validity"] == "NOT_VALID_FOR_TRADING"
    assert rec["reason_codes"] == ["LLM_REPAIR_TRADE_INVALID"]


def test_ui_cleanup_preserves_strategy():
    from momentum_companion.ui.controller import UIController  # type: ignore

    parsed = {
        "summary": "Break $above level.",
        "setups": [
            {"trigger_condition": "break $10.5", "confirmation_requirements": "hold", "name": "s", "extension_notes": "$", "extension_trigger": "$", "target1_label": "$nearest_resistance"}
        ],
    }
    cleaned = UIController._apply_pullback_guard(parsed, current_price=10.0)
    assert cleaned["setups"][0]["trigger_condition"] == "break 10.5"
    assert cleaned["summary"] == "Break above level."
