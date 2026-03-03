from momentum_companion.ui.controller import UIController


def test_pullback_sentence_added_when_entry_below_price():
    rec = {
        "summary": "Base summary.",
        "setups": [
            {"trigger_condition": "break 4.31", "entry_trigger_price": 4.31},
        ],
    }
    out = UIController._apply_pullback_guard(rec, current_price=4.54)
    assert out["summary"].startswith("This is a pullback/retest plan, not a buy-now entry.")
    tc = out["setups"][0]["trigger_condition"].lower()
    assert "retest" in tc or "pullback" in tc or "reclaim" in tc


def test_breakout_not_forced_when_price_below_entry():
    rec = {
        "summary": "Breakout ok.",
        "setups": [
            {"trigger_condition": "break 4.31", "entry_trigger_price": 4.31},
        ],
    }
    out = UIController._apply_pullback_guard(rec, current_price=4.28)
    assert out["summary"].startswith("Breakout ok.")
    tc = out["setups"][0]["trigger_condition"].lower()
    assert "pullback" not in tc and "retest" not in tc and "reclaim" not in tc
