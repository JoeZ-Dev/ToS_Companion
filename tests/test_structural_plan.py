from momentum_companion.ui.controller import UIController


def _make_controller() -> UIController:
    # Bypass __init__ heavy wiring
    return UIController.__new__(UIController)


def test_structural_plan_prefers_micro_over_far_resistance():
    ctl = _make_controller()
    payload = {
        "quote": {"last": 1.0, "ask": 1.0},
        "levels": {
            "nearest_resistance": {"price": 1.6},  # far (60%) should be rejected
            "nearest_support": {"price": 0.92},
        },
        "micro": {"micro_resistance_15m": 1.15, "micro_support_15m": 0.93},
        "bars_window": [],
    }
    plan = ctl._build_structural_plan(payload)
    assert plan["target_candidate"] == 1.15
    assert plan["target_source"] == "micro_resistance_15m"
    # RR: (1.15-1.0)/(1.0-0.92)=0.15/0.08=1.875 <2 so plan should be invalid but keep candidates
    assert plan["valid"] is False
    assert plan["entry_candidate"] == 1.0
    assert plan["stop_candidate"] == 0.92
    assert plan["rr_candidate"] and plan["rr_candidate"] < 2
    assert "RR_BELOW_MINIMUM" in plan["invalid_reasons"]


def test_structural_plan_valid_rejects_no_clear_level():
    ctl = _make_controller()
    normalized = {
        "structural_plan": {
            "entry_candidate": 1.0,
            "stop_candidate": 0.9,
            "target_candidate": 1.2,
            "rr_candidate": 2.0,
            "valid": True,
        }
    }
    rec = {"validity": "NOT_VALID_FOR_TRADING", "reason_codes": ["NO_CLEAR_LEVEL"], "entry_price": None, "stop_loss": None, "target_price": None, "risk_reward": None}
    ok, reason = ctl._validate_llm_response_consistency(normalized, rec)
    assert ok is False
    assert reason == "NO_CLEAR_LEVEL_CONTRADICTS_STRUCTURAL_PLAN"


def test_structural_plan_normal_case_uses_swing_high():
    ctl = _make_controller()
    bars = []
    # create highs up to 1.1 within lookback
    for i in range(30):
        bars.append({"h": 1.05 + (0.002 * i), "l": 0.99})
    payload = {
        "quote": {"last": 1.0, "ask": 1.0},
        "levels": {"nearest_resistance": {"price": 1.04}, "nearest_support": {"price": 0.98}},
        "micro": {},
        "bars_window": bars,
    }
    plan = ctl._build_structural_plan(payload)
    assert plan["target_source"] == "swing_high"
    assert plan["target_candidate"] > plan["entry_candidate"]
    assert plan["valid"] in {True, False}  # ensure no exception


def test_structural_plan_target_too_far_marks_reason():
    ctl = _make_controller()
    payload = {
        "quote": {"last": 1.0, "ask": 1.0},
        "levels": {
            "nearest_resistance": {"price": 1.35},  # 35% away, beyond MAX_TARGET_PCT=0.20
            "nearest_support": {"price": 0.9},
        },
        "micro": {},
        "bars_window": [],
    }
    plan = ctl._build_structural_plan(payload)
    assert plan["target_candidate"] == 1.35  # still reported for diagnostics
    assert plan["valid"] is False
    assert "TARGET_TOO_FAR" in plan["invalid_reasons"]


def test_structural_plan_ignores_stop_above_entry_and_falls_back():
    ctl = _make_controller()
    payload = {
        "quote": {"last": 1.0, "ask": 1.0},
        "levels": {
            "nearest_resistance": {"price": 1.1},
            "nearest_support": {"price": 1.05},  # above entry, should be ignored
        },
        "micro": {"micro_support_15m": 0.9},
        "bars_window": [],
    }
    plan = ctl._build_structural_plan(payload)
    assert plan["stop_candidate"] == 0.9  # fell back to micro support below entry
    assert plan["stop_source"] == "micro_support_15m"
