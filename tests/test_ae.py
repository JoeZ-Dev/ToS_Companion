import pytest

pd = pytest.importorskip("pandas")  # noqa: F401

from momentum_companion.analysis.ae import AEEngine, OneMinuteBar


def _make_engine_with_profile(symbol="SYM"):
    eng = AEEngine(None, None)
    eng._profile_cache[symbol] = {
        "symbol": symbol,
        "is_above_4h_ema": True,
        "prior_close": 10.0,
        "htf_high": 50.0,
        "resistance_clusters": [],
        "support_clusters": [],
    }
    return eng


def test_is_above_open_uses_rth_open():
    eng = _make_engine_with_profile()
    eng._session_open_rth["SYM"] = 10.0
    eng._minute_agg._bars = [OneMinuteBar(ts=0, open=10.5, high=11.0, low=10.0, close=11.0, volume=100, is_extended=False)]
    snap = eng._build_snapshot()
    assert snap["regime"]["is_above_open"] is True


def test_is_above_open_null_when_missing_rth_open():
    eng = _make_engine_with_profile()
    eng._minute_agg._bars = [OneMinuteBar(ts=0, open=10.5, high=11.0, low=10.0, close=9.0, volume=100, is_extended=False)]
    snap = eng._build_snapshot()
    assert snap["regime"]["is_above_open"] is None


def test_cluster_selection_relative_to_price():
    eng = _make_engine_with_profile()
    eng._session_open_rth["SYM"] = 10.0
    eng._minute_agg._bars = [OneMinuteBar(ts=0, open=10.0, high=10.0, low=10.0, close=10.0, volume=100, is_extended=False)]
    eng._profile_cache["SYM"]["resistance_clusters"] = [
        {"price_zone_low": 8.0, "price_zone_high": 8.2, "strength_score": 0.9},
        {"price_zone_low": 10.5, "price_zone_high": 10.7, "strength_score": 0.8},
        {"price_zone_low": 12.0, "price_zone_high": 12.3, "strength_score": 0.7},
    ]
    eng._profile_cache["SYM"]["support_clusters"] = [
        {"price_zone_low": 9.0, "price_zone_high": 9.1, "strength_score": 0.6},
        {"price_zone_low": 11.0, "price_zone_high": 11.1, "strength_score": 0.5},
    ]
    snap = eng._build_snapshot()
    res = snap["levels"]["resistance_clusters"]
    sup = snap["levels"]["support_clusters"]
    assert all(((c["price_zone_low"] + c["price_zone_high"]) / 2) >= 10.0 for c in res)
    assert all(((c["price_zone_low"] + c["price_zone_high"]) / 2) <= 10.0 for c in sup)
    nr = snap["levels"]["nearest_resistance"]
    ns = snap["levels"]["nearest_support"]
    assert nr is not None and nr["price"] >= 10.0 and nr["distance_pct"] >= 0
    assert ns is not None and ns["price"] <= 10.0 and ns["distance_pct"] <= 0
