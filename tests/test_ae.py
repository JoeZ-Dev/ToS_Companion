import pytest

pd = pytest.importorskip("pandas")  # noqa: F401

from momentum_companion.analysis.ae import AEEngine, OneMinuteBar, _compute_micro_metrics
from momentum_companion.data.bar_aggregator import TenSecondBar
from datetime import datetime
from zoneinfo import ZoneInfo


def _ts(day, hour, minute, second=0):
    return int(datetime(2026, 9, day, hour, minute, second, tzinfo=ZoneInfo("America/New_York")).timestamp())


def test_seed_and_midminute_live_volume_use_hlc3_once_and_match_chart_series():
    engine = AEEngine(None, None)
    minute = _ts(22, 9, 35)
    engine.seed_intraday_from_bars("ABC", [
        {"time": minute - 60, "open": 10, "high": 12, "low": 9, "close": 12, "volume": 100},
        {"time": minute, "open": 20, "high": 24, "low": 18, "close": 21, "volume": 30},
    ], end_ms=(minute + 25) * 1000)
    agg = engine._minute_agg
    seeded_num = 11 * 100 + 21 * 30
    assert agg.vwap() == pytest.approx(seeded_num / 130)
    assert agg.vwap_points[-1]["value"] == pytest.approx(agg.vwap())
    engine.ingest_10s_bar(TenSecondBar(minute + 10, 99, 99, 99, 99, 999, False))
    assert agg.vwap_den == 130  # Fully covered interval ending before :25
    # The 09:35:20 interval began before the :25 REST cutoff but contains
    # incremental live volume only after the fresh L1 baseline.
    snapshot = engine.ingest_10s_bar(TenSecondBar(minute + 20, 30, 33, 27, 30, 10, False))
    assert snapshot["vwap"] == pytest.approx((seeded_num + 30 * 10) / 140)
    engine.ingest_10s_bar(TenSecondBar(minute + 30, 40, 42, 36, 39, 20, False))
    expected = (seeded_num + 300 + 39 * 20) / 160
    assert engine._minute_agg.vwap() == pytest.approx(expected)
    assert engine._minute_agg.vwap_points[-1]["value"] == pytest.approx(expected)
    engine.ingest_10s_bar(TenSecondBar(minute + 60, 50, 50, 50, 50, 5, False))
    assert engine._minute_agg.vwap_den == 165
    assert engine._minute_agg.bars[-1].volume == 60  # 30 seed + 10 + 20 live


def test_vwap_resets_on_new_ny_day_and_seed_excludes_future_or_older_days():
    engine = AEEngine(None, None)
    ts = _ts(22, 23, 59)
    engine.seed_intraday_from_bars("ABC", [
        {"time": ts - 86400, "open": 5, "high": 5, "low": 5, "close": 5, "volume": 100},
        {"time": ts, "open": 10, "high": 12, "low": 9, "close": 12, "volume": 100},
        {"time": ts + 86400, "open": 99, "high": 99, "low": 99, "close": 99, "volume": 100},
    ], end_ms=(ts + 20) * 1000)
    assert engine._minute_agg.vwap() == pytest.approx(11)
    engine.ingest_10s_bar(TenSecondBar(_ts(23, 0, 0), 20, 24, 18, 21, 10, False))
    assert engine._minute_agg.vwap() == pytest.approx(21)
    assert len(engine._minute_agg.vwap_points) == 1


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


def test_compute_micro_metrics_coil_state():
    bars = []
    # First 10 bars wide range
    for i in range(10):
        bars.append(OneMinuteBar(ts=i * 60, open=10.0, high=10.5, low=9.5, close=10.0, volume=100, is_extended=False))
    # Last 5 bars tight range
    for j in range(5):
        bars.append(OneMinuteBar(ts=(10 + j) * 60, open=10.0, high=10.1, low=9.9, close=10.0, volume=100, is_extended=False))
    micro = _compute_micro_metrics(bars, 10.0)
    assert micro["micro_resistance_15m"] == 10.5
    assert micro["micro_support_15m"] == 9.5
    assert pytest.approx(micro["range_5m_pct"], rel=1e-3) == 2.0
    assert pytest.approx(micro["range_15m_pct"], rel=1e-3) == 10.0
    assert pytest.approx(micro["compression_ratio"], rel=1e-3) == 0.2
    assert micro["micro_state"] == "COIL"
    assert pytest.approx(micro["dist_to_micro_r_pct"], rel=1e-3) == 5.0


def test_micro_metrics_in_snapshot():
    eng = _make_engine_with_profile()
    eng._session_open_rth["SYM"] = 10.0
    bars = []
    for i in range(10):
        bars.append(OneMinuteBar(ts=i * 60, open=10.0, high=10.5, low=9.5, close=10.0, volume=100, is_extended=False))
    for j in range(5):
        bars.append(OneMinuteBar(ts=(10 + j) * 60, open=10.0, high=10.1, low=9.9, close=10.0, volume=100, is_extended=False))
    eng._minute_agg._bars = bars
    snap = eng._build_snapshot()
    micro = snap["micro"]
    assert micro["micro_state"] == "COIL"
    assert micro["micro_resistance_15m"] == 10.5


def test_levels_book_influence_scoring():
    eng = _make_engine_with_profile()
    eng._session_open_rth["SYM"] = 10.0
    bars = []
    # 30 bars, with 5 touching a resistance zone at 10.0-10.1
    for i in range(25):
        bars.append(OneMinuteBar(ts=i * 60, open=9.5, high=9.7, low=9.4, close=9.6, volume=100, is_extended=False))
    for i in range(25, 30):
        # touches and slight rejections
        bars.append(OneMinuteBar(ts=i * 60, open=9.9, high=10.1, low=9.8, close=9.9, volume=150, is_extended=False))
    eng._minute_agg._bars = bars
    eng._profile_cache["SYM"]["resistance_clusters"] = [
        {"price_zone_low": 10.0, "price_zone_high": 10.1, "strength_score": 0.9}
    ]
    snap = eng._build_snapshot()
    levels_book = snap["levels_book"]
    assert levels_book
    top = levels_book[0]
    assert top["dynamic_influence"] > top["base_strength"]
    # distance decay should keep distance small
    assert abs(top["distance_pct"]) < 5


def test_manual_pre7_seed_is_included_before_post7_hlc3_bars():
    engine = AEEngine(None, None)
    minute = _ts(24, 7, 0)
    bars = [
        {"time": _ts(24, 6, 59), "open": 99.0, "high": 99.0, "low": 99.0, "close": 99.0, "volume": 999999},
        {"time": minute, "open": 3.0, "high": 3.2, "low": 2.8, "close": 3.1, "volume": 1000},
        {"time": minute + 60, "open": 3.1, "high": 3.4, "low": 3.0, "close": 3.3, "volume": 2000},
    ]

    engine.seed_intraday_from_bars(
        "GCTK",
        bars,
        end_ms=(minute + 120) * 1000,
        pre7_vwap=4.4233,
        pre7_volume=10570235,
    )

    post7_num = ((3.2 + 2.8 + 3.1) / 3) * 1000 + ((3.4 + 3.0 + 3.3) / 3) * 2000
    expected = (4.4233 * 10570235 + post7_num) / (10570235 + 3000)
    assert engine._minute_agg.vwap() == pytest.approx(expected)
    assert engine._minute_agg.vwap_den == pytest.approx(10570235 + 3000)
    assert engine.vwap_points[-1]["value"] == pytest.approx(expected)
