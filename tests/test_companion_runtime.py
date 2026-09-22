from datetime import datetime
from zoneinfo import ZoneInfo
import threading

from momentum_companion.data.bar_aggregator import TenSecondBar
from momentum_companion.runtime import CompanionRuntime
from momentum_companion.session import CompanionSession


class FakeStream:
    def __init__(self):
        self.symbol_sets = []
        self.unsubscribed = []

    def subscribe_level_one_symbols(self, symbols):
        self.symbol_sets.append(list(symbols))

    def unsubscribe(self, symbol):
        self.unsubscribed.append(symbol)


class FakeRecorder:
    def __init__(self):
        self.payloads = []
        self.symbols = []
        self._active = []

    def record_payload(self, payload):
        self.payloads.append(payload)

    def add_symbol(self, symbol):
        if symbol not in self.symbols:
            self.symbols.append(symbol)
        if symbol not in self._active:
            self._active.append(symbol)
        return True

    def remove_symbol(self, symbol):
        if symbol in self._active:
            self._active.remove(symbol)
        return True

    def active_symbols(self):
        return list(self._active)

    def state(self):
        return {"active": True, "symbols": list(self.symbols), "active_symbols": list(self._active)}


class FakeAppState:
    def get(self, key):
        if key == "llm_full_model":
            return "test-model"
        return None


class FakeLLMClient:
    def is_available(self):
        return True


class FakeLLMService:
    def __init__(self):
        self.calls = []
        self._client = object()

    def evaluate(self, snapshot, session_mode, quote, model_override=None, messages_override=None):
        self.calls.append(
            {
                "snapshot": snapshot,
                "session_mode": session_mode,
                "quote": quote,
                "model_override": model_override,
                "messages_override": messages_override,
            }
        )
        return {"stock_bias": "NO_EDGE", "setups": []}


class FakeCoach:
    system_prompt = "test prompt"


def bare_runtime():
    runtime = CompanionRuntime.__new__(CompanionRuntime)
    runtime.session = CompanionSession()
    runtime._lock = threading.RLock()
    runtime._active_symbol = "AEHL"
    runtime._recording_symbols = {"TOPS", "DDC"}
    runtime._stream = FakeStream()
    runtime._recorder = None
    runtime._et_tz = ZoneInfo("America/New_York")
    return runtime


def test_desired_stream_symbols_union_active_and_recording_symbols():
    runtime = bare_runtime()

    runtime._refresh_stream_subscription()

    assert runtime._stream.symbol_sets[-1] == ["AEHL", "DDC", "TOPS"]


def test_raw_payload_is_routed_only_when_recording_active():
    runtime = bare_runtime()
    recorder = FakeRecorder()
    runtime._recorder = recorder

    payload = {"data": [{"service": "LEVELONE_EQUITIES"}]}
    runtime._handle_raw_payload(payload)

    assert recorder.payloads == [payload]


def test_headless_llm_updates_session_state():
    runtime = bare_runtime()
    runtime.app_state = FakeAppState()
    runtime.llm_coach = FakeCoach()
    runtime._llm_client = FakeLLMClient()
    runtime.llm_service = FakeLLMService()

    runtime.session.add_symbol("AEHL", make_active=True)
    runtime.session.ingest_quote(
        {
            "ts_ms": 1,
            "symbol": "AEHL",
            "bid": 3.1,
            "ask": 3.2,
            "last": 3.15,
            "bid_size": 1,
            "ask_size": 1,
            "last_size": 1,
            "volume": 100,
            "source_ts_type": "TRADE_TS",
            "raw_source": "SCHWAB_STREAM",
        }
    )
    runtime.session.update_ae_snapshot(
        "AEHL",
        {"symbol": "AEHL", "status": "ok", "data_quality": "ok"},
    )

    result = runtime.run_llm("AEHL")

    assert result["stock_bias"] == "NO_EDGE"
    assert runtime.session.snapshot()["symbols"]["AEHL"]["llm_output"] == result
    assert runtime.llm_service.calls[0]["model_override"] is None


def test_session_mode_distinguishes_premarket_rth_and_postmarket():
    runtime = bare_runtime()
    runtime._et_tz = ZoneInfo("America/New_York")

    assert runtime.session_mode(datetime(2026, 9, 22, 8, 0, tzinfo=runtime._et_tz)) == "PRE"
    assert runtime.session_mode(datetime(2026, 9, 22, 10, 0, tzinfo=runtime._et_tz)) == "RTH"
    assert runtime.session_mode(datetime(2026, 9, 22, 17, 0, tzinfo=runtime._et_tz)) == "POST"
    assert runtime.session_mode(datetime(2026, 9, 22, 21, 0, tzinfo=runtime._et_tz)) == "CLOSED"


class FakeHistoryRest:
    def __init__(self):
        self.calls = []

    def fetch_price_history(self, symbol, start_ms, end_ms, freq):
        self.calls.append((symbol, start_ms, end_ms, freq))
        return {
            "candles": [
                {
                    "datetime": start_ms + 60_000,
                    "open": 5.0,
                    "high": 5.2,
                    "low": 4.9,
                    "close": 5.1,
                    "volume": 1000,
                }
            ]
        }


def test_chart_history_requests_one_minute_intraday_window(monkeypatch):
    runtime = bare_runtime()
    runtime.rest = FakeHistoryRest()
    runtime._et_tz = ZoneInfo("America/New_York")

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 9, 22, 5, 30, tzinfo=ZoneInfo("America/New_York"))
            return value if tz else value.replace(tzinfo=None)

    import momentum_companion.runtime.companion_runtime as runtime_module
    monkeypatch.setattr(runtime_module, "datetime", FixedDateTime)

    runtime._load_history("IMCC")

    symbol, start_ms, end_ms, freq = runtime.rest.calls[-1]
    start_et = datetime.fromtimestamp(start_ms / 1000, tz=ZoneInfo("America/New_York"))
    assert symbol == "IMCC"
    assert freq == "1m"
    assert (start_et.hour, start_et.minute) == (4, 0)
    assert end_ms > start_ms
    assert runtime.session.snapshot()["symbols"]["IMCC"]["history_bars"]


class FakePatternService:
    def __init__(self):
        self.calls = []

    def ingest_completed_bar(self, symbol, bar):
        self.calls.append((symbol, bar))
        return [{
            "id": f"{symbol}:TEST_PATTERN:{bar.ts}",
            "symbol": symbol,
            "pattern_type": "TEST_PATTERN",
            "state": "FORMING",
            "evidence": {"bar_ts": bar.ts},
            "points": [],
            "lines": [],
        }]


class FakeAEEngineForPatterns:
    def __init__(self):
        self.bars = []

    def ingest_10s_bar(self, bar):
        self.bars.append(bar)
        return {"status": "ok", "symbol": "AEHL"}


def test_completed_bar_updates_patterns_and_preserves_ae_processing():
    runtime = bare_runtime()
    runtime.pattern_service = FakePatternService()
    runtime.ae_engine = FakeAEEngineForPatterns()
    bar = TenSecondBar(
        ts=10,
        open=3.0,
        high=3.2,
        low=2.9,
        close=3.1,
        volume=100,
        is_extended=True,
    )

    runtime._handle_completed_bar("AEHL", bar)

    symbol_state = runtime.session.snapshot()["symbols"]["AEHL"]
    assert runtime.pattern_service.calls == [("AEHL", bar)]
    assert symbol_state["pattern_observations"][0]["pattern_type"] == "TEST_PATTERN"
    assert symbol_state["ae_snapshot"]["status"] == "ok"
    assert runtime.ae_engine.bars == [bar]


def test_runtime_add_remove_recording_symbol_refreshes_stream_union(monkeypatch):
    import momentum_companion.runtime.companion_runtime as runtime_module
    monkeypatch.setattr(runtime_module, "reached_cutoff", lambda: False)
    runtime = bare_runtime()
    recorder = FakeRecorder()
    runtime._recorder = recorder
    runtime._recording_symbols = set()

    added = runtime.add_recording_symbol("tops")
    assert added["active_symbols"] == ["TOPS"]
    assert runtime._stream.symbol_sets[-1] == ["AEHL", "TOPS"]

    removed = runtime.remove_recording_symbol("TOPS")
    assert removed["active_symbols"] == []
    assert runtime._stream.unsubscribed[-1] == "TOPS"
    assert runtime._stream.symbol_sets[-1] == ["AEHL"]
