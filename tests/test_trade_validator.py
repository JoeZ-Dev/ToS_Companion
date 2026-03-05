from momentum_companion.llm.validator import validate_trade_setups


def _sample_snapshot():
    return {"session": {"premarket_high": 2.5, "premarket_low": 2.0}}


def test_accepts_reasonable_setup():
    snap = _sample_snapshot()
    llm = {
        "stock_bias": "HAS_POTENTIAL",
        "setups": [
            {"entry_trigger_price": 2.22, "stop_price": 2.07, "target_price": 2.39, "setup_rating": "B"},
        ],
    }
    ok, reasons, action = validate_trade_setups(snap, llm)
    assert ok
    assert not reasons
    assert action == "OK"


def test_rejects_trivial_target():
    snap = _sample_snapshot()
    llm = {
        "stock_bias": "HAS_POTENTIAL",
        "setups": [
            {"entry_trigger_price": 2.22, "stop_price": 2.07, "target_price": 2.23, "setup_rating": "B-"},
        ],
    }
    ok, reasons, action = validate_trade_setups(snap, llm)
    assert not ok
    assert action == "RETRY"
    assert any("move_pct" in r or "rr" in r for r in reasons)
