from momentum_companion.ui.controller import UIController


def test_stock_bias_actionable():
    rec = {
        "stock_bias": "NO_EDGE",
        "summary": "test",
        "setups": [
            {
                "name": "s",
                "trigger_condition": "break 4.5",
                "entry_trigger_price": 4.5,
                "stop_price": 4.2,
                "target_price": 5.1,
                "rr_to_target1": 2.0,
                "move_pct_to_target1": 0.13,
                "setup_rating": "A-",
                "confirmation_requirements": "hold",
                "target1_label": "nearest_resistance",
                "extension_trigger": "",
                "extension_target": None,
                "extension_notes": "",
                "tape_warning": "NONE",
            }
        ],
    }
    guard = UIController._apply_pullback_guard(rec, current_price=4.0)
    out, ok, _ = UIController._validate_llm_output(guard, current_price=4.0)
    assert out["stock_bias"] == "HAS_POTENTIAL"
    assert ok


def test_stock_bias_no_edge_when_weak():
    rec = {
        "stock_bias": "HAS_POTENTIAL",
        "summary": "test",
        "setups": [
            {
                "name": "s",
                "trigger_condition": "break 4.5",
                "entry_trigger_price": 4.5,
                "stop_price": 4.4,
                "target_price": 4.55,
                "rr_to_target1": 0.5,
                "move_pct_to_target1": 0.011,
                "setup_rating": "B-",
                "confirmation_requirements": "hold",
                "target1_label": "nearest_resistance",
                "extension_trigger": "",
                "extension_target": None,
                "extension_notes": "",
                "tape_warning": "NONE",
            }
        ],
    }
    guard = UIController._apply_pullback_guard(rec, current_price=4.4)
    out, ok, reasons = UIController._validate_llm_output(guard, current_price=4.4)
    assert out["stock_bias"] == "NO_EDGE"
    assert not ok
    assert any("rating too high" in r or "rr" in r for r in reasons)


def test_near_price_requires_close_hold():
    rec = {
        "stock_bias": "NO_EDGE",
        "summary": "test",
        "setups": [
            {
                "name": "s",
                "trigger_condition": "reclaim 4.50",
                "entry_trigger_price": 4.5,
                "stop_price": 4.3,
                "target_price": 4.8,
                "rr_to_target1": 1.5,
                "move_pct_to_target1": 0.066,
                "setup_rating": "B",
                "confirmation_requirements": "hold",
                "target1_label": "nearest_resistance",
                "extension_trigger": "",
                "extension_target": None,
                "extension_notes": "",
                "tape_warning": "NONE",
            }
        ],
    }
    guard = UIController._apply_pullback_guard(rec, current_price=4.49)
    out, ok, _ = UIController._validate_llm_output(guard, current_price=4.49)
    tc = out["setups"][0]["trigger_condition"].lower()
    assert "close" in tc
    assert "hold" in tc or "retest" in tc


def test_currency_symbols_removed():
    rec = {
        "stock_bias": "NO_EDGE",
        "summary": "$test",
        "setups": [
            {
                "name": "$name",
                "trigger_condition": "close $4.5",
                "entry_trigger_price": 4.5,
                "stop_price": 4.3,
                "target_price": 4.8,
                "rr_to_target1": 1.5,
                "move_pct_to_target1": 0.066,
                "setup_rating": "B",
                "confirmation_requirements": "hold",
                "target1_label": "$nearest_resistance",
                "extension_trigger": "$",
                "extension_target": None,
                "extension_notes": "$note",
                "tape_warning": "NONE",
            }
        ],
    }
    guard = UIController._apply_pullback_guard(rec, current_price=4.49)
    out, _, _ = UIController._validate_llm_output(guard, current_price=4.49)
    assert "$" not in out["summary"]
    for k in ("name", "trigger_condition", "target1_label", "extension_trigger", "extension_notes"):
        assert "$" not in out["setups"][0][k]
