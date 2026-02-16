import pytest

websocket = pytest.importorskip("websocket")

from momentum_companion.clients.token_provider import TokenProvider
from momentum_companion.clients.schwab_stream import SchwabStreamClient
from momentum_companion.llm.service import LLMService
from momentum_companion.llm.coach import LLMCoach
from momentum_companion.execution.trade_executor import TradeExecutor
from momentum_companion.execution.emm_engine import EMMEngine
from momentum_companion.triggers.synthetic import SyntheticTriggerEngine


def test_token_provider_sets_auth_required(tmp_path):
    states = []
    provider = TokenProvider(token_path=tmp_path / "tokens.json", state_callback=states.append)
    provider._token_cache["refresh_token"] = "rt"  # inject
    provider.refresh()
    assert "AUTH_REQUIRED" in states


def test_stream_emits_stream_down(monkeypatch):
    states = []

    def no_sleep(_):
        return None

    monkeypatch.setattr("momentum_companion.clients.schwab_stream.time.sleep", no_sleep)

    client = SchwabStreamClient(
        {
            "streamerSocketUrl": "wss://example",
            "schwabClientCustomerId": "",
            "schwabClientCorrelId": "",
            "schwabClientChannel": "",
            "schwabClientFunctionId": "",
            "access_token": "",
        },
        lambda e: None,
        token_provider=None,
        journal=None,
        state_callback=states.append,
    )

    def fail_connect():
        raise RuntimeError("fail")

    monkeypatch.setattr(client, "connect", fail_connect)
    client._attempt_reconnect()
    assert "STREAM_DOWN" in states


class BadCoach(LLMCoach):
    def run(self, payload, context):
        return {"validity": "BAD", "reason_codes": ["X"], "setup_rating": "A"}

    def validate_response(self, resp):
        return True


def test_llm_invalid_output_sets_state(tmp_path):
    states = []
    svc = LLMService(BadCoach(), client=None, journal=None, state_callback=states.append)
    resp = svc.evaluate({"symbol": "AAPL", "as_of_ts_ms": 1}, "SEAMLESS", {"bid": 1, "ask": 2})
    assert "LLM_INVALID_OUTPUT" in states
    assert resp["validity"] == "NOT_VALID_FOR_TRADING"


def test_unknown_working_orders_sets_state(monkeypatch):
    states = []

    def fake_check(rest_client, account_id, local_orders, symbol=None):
        return False

    monkeypatch.setattr("momentum_companion.execution.trade_executor.check_unknown_working", fake_check)

    class DummyJournal:
        def __init__(self):
            self.events = []

        def append_event(self, event):
            self.events.append(event)

    executor = TradeExecutor(
        rest_client=None,
        emm_engine=EMMEngine(None),
        trigger_engine=SyntheticTriggerEngine(None),
        journal=DummyJournal(),
        state_callback=states.append,
    )
    # Build minimal order_spec
    res = executor.submit_order({"account_id": "acc", "order_payload": {}, "symbol": "AAPL", "session_mode": "SEAMLESS"})
    assert res == "gate_closed"
    assert "UNKNOWN_WORKING_ORDERS" in states
