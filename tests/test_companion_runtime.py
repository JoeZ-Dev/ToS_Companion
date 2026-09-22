from datetime import datetime
from zoneinfo import ZoneInfo
import threading

from momentum_companion.runtime import CompanionRuntime
from momentum_companion.session import CompanionSession


class FakeStream:
    def __init__(self):
        self.symbol_sets = []

    def subscribe_level_one_symbols(self, symbols):
        self.symbol_sets.append(list(symbols))


class FakeRecorder:
    def __init__(self):
        self.payloads = []

    def record_payload(self, payload):
        self.payloads.append(payload)


class FakeAppState:
    def get(self, key):
        if key == "llm_full_model":
            return "test-model"
        return None


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
    assert runtime.llm_service.calls[0]["model_override"] == "test-model"


def test_session_mode_distinguishes_premarket_rth_and_postmarket():
    runtime = bare_runtime()
    runtime._et_tz = ZoneInfo("America/New_York")

    assert runtime.session_mode(datetime(2026, 9, 22, 8, 0, tzinfo=runtime._et_tz)) == "PRE"
    assert runtime.session_mode(datetime(2026, 9, 22, 10, 0, tzinfo=runtime._et_tz)) == "RTH"
    assert runtime.session_mode(datetime(2026, 9, 22, 17, 0, tzinfo=runtime._et_tz)) == "POST"
    assert runtime.session_mode(datetime(2026, 9, 22, 21, 0, tzinfo=runtime._et_tz)) == "CLOSED"
