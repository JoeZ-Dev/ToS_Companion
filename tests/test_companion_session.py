from momentum_companion.data.bar_aggregator import TenSecondBar
from momentum_companion.session import CompanionSession


def quote(symbol="AEHL", last=3.21):
    return {
        "ts_ms": 1_700_000_000_000,
        "symbol": symbol,
        "bid": last - 0.01,
        "ask": last + 0.01,
        "last": last,
        "bid_size": 100,
        "ask_size": 200,
        "last_size": 50,
        "volume": 123_456,
        "source_ts_type": "TRADE_TS",
        "raw_source": "SCHWAB_STREAM",
    }


def test_session_is_multi_symbol_and_normalizes_symbols():
    session = CompanionSession()
    session.add_symbol(" aehl ")
    session.add_symbol("tops")

    assert session.watched_symbols() == ["AEHL", "TOPS"]
    assert session.snapshot()["active_symbol"] == "AEHL"


def test_quote_updates_headless_state_and_emits_serializable_event():
    session = CompanionSession()
    events = []
    unsubscribe = session.subscribe(events.append)

    session.ingest_quote(quote())
    unsubscribe()

    snap = session.snapshot()
    assert snap["symbols"]["AEHL"]["quote"]["last"] == 3.21
    assert events[-1]["type"] == "quote"
    assert events[-1]["symbol"] == "AEHL"
    assert events[-1]["payload"]["volume"] == 123_456


def test_completed_bars_are_bounded_per_symbol():
    session = CompanionSession(max_bars_per_symbol=2)

    for ts in (10, 20, 30):
        session.ingest_bar(
            "AEHL",
            TenSecondBar(
                ts=ts,
                open=3.0,
                high=3.2,
                low=2.9,
                close=3.1,
                volume=100,
                is_extended=True,
            ),
        )

    bars = session.snapshot()["symbols"]["AEHL"]["bars_10s"]
    assert [bar["ts"] for bar in bars] == [20, 30]


def test_removing_active_symbol_promotes_next_watched_symbol():
    session = CompanionSession()
    session.add_symbol("AEHL")
    session.add_symbol("TOPS")

    assert session.remove_symbol("AEHL") is True
    assert session.snapshot()["active_symbol"] == "TOPS"


def test_connection_and_analysis_state_are_ui_agnostic():
    session = CompanionSession()
    session.update_connection_state("connected")
    session.update_ae_snapshot("AEHL", {"state": "READY"})
    session.update_llm_output("AEHL", {"validity": "VALID"})
    session.update_trade_state("AEHL", {"position": "flat"})
    session.update_recorder_state({"active": True, "symbols": ["AEHL"]})

    snap = session.snapshot()
    assert snap["connection_state"] == "CONNECTED"
    assert snap["symbols"]["AEHL"]["ae_snapshot"] == {"state": "READY"}
    assert snap["symbols"]["AEHL"]["llm_output"] == {"validity": "VALID"}
    assert snap["symbols"]["AEHL"]["trade_state"] == {"position": "flat"}
    assert snap["recorder_state"]["active"] is True


def test_bad_subscriber_cannot_break_market_state():
    session = CompanionSession()

    def broken(_event):
        raise RuntimeError("browser went away")

    session.subscribe(broken)
    session.ingest_quote(quote())

    assert session.snapshot()["symbols"]["AEHL"]["quote"]["last"] == 3.21


def test_history_is_exposed_for_browser_chart():
    session = CompanionSession()
    session.set_history(
        "AEHL",
        [{"time": 10, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 50}],
    )

    snap = session.snapshot()
    assert snap["symbols"]["AEHL"]["history_bars"][0]["close"] == 1.5


def test_pattern_observations_are_exposed_and_emitted_for_browser_clients():
    session = CompanionSession()
    events = []
    unsubscribe = session.subscribe(events.append)
    session.update_pattern_observations(
        "AEHL",
        [{
            "id": "AEHL:MICRO_PULLBACK:10",
            "symbol": "AEHL",
            "pattern_type": "MICRO_PULLBACK",
            "state": "TURNING",
            "evidence": {"duration_sec": 40},
            "points": [],
            "lines": [],
        }],
    )
    unsubscribe()

    snap = session.snapshot()
    patterns = snap["symbols"]["AEHL"]["pattern_observations"]
    assert patterns[0]["pattern_type"] == "MICRO_PULLBACK"
    assert patterns[0]["evidence"]["duration_sec"] == 40
    assert events[-1]["type"] == "pattern_update"
    assert events[-1]["payload"]["patterns"][0]["state"] == "TURNING"
