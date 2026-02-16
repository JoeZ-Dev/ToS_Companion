from momentum_companion.execution.trade_executor import TradeExecutor
from momentum_companion.execution.emm_engine import EMMEngine
from momentum_companion.triggers.synthetic import SyntheticTriggerEngine
from momentum_companion.journal.writer import JournalWriter
from momentum_companion.data.schema import init_db
from momentum_companion.gates import TradingGateState


class DummyRest:
    def __init__(self):
        self.canceled = []

    def cancel_order(self, account_id, order_id):
        self.canceled.append(order_id)

    def place_order(self, *args, **kwargs):
        return "oid"


def test_cancel_all_calls_rest_and_disarms(tmp_path):
    db_path = tmp_path / "data.db"
    init_db(db_path)
    journal = JournalWriter(db_path)
    rest = DummyRest()
    emm = EMMEngine(rest)
    trig = SyntheticTriggerEngine(None)
    exec = TradeExecutor(rest, emm, trig, journal)
    exec.cancel_all("acc1", ["1", "2"], "AAPL")
    assert rest.canceled == ["1", "2"]
    # flatten should also journal
    exec.flatten_position("AAPL")


def test_emm_failure_journal(tmp_path):
    db_path = tmp_path / "data.db"
    init_db(db_path)
    journal = JournalWriter(db_path)
    rest = DummyRest()
    emm = EMMEngine(rest)
    trig = SyntheticTriggerEngine(None)
    exec = TradeExecutor(rest, emm, trig, journal)
    exec.journal_emm_failure("AAPL", "NO_QUOTE", last_quote_age_ms=6000)


def test_unknown_working_orders_gate(tmp_path):
    db_path = tmp_path / "data.db"
    init_db(db_path)
    journal = JournalWriter(db_path)

    class RestWithOrders(DummyRest):
        def get_orders(self, account_id):
            return [{"orderId": "999", "symbol": "AAPL", "status": "WORKING"}]

    rest = RestWithOrders()
    emm = EMMEngine(rest)
    trig = SyntheticTriggerEngine(None)
    exec = TradeExecutor(rest, emm, trig, journal)
    gate = TradingGateState(auth_ok=True, stream_connected=True, quote_fresh=True, journal_healthy=True, reconciliation_complete=True)
    result = exec.submit_order(
        {"account_id": "acc", "symbol": "AAPL", "session_mode": "NORMAL", "order_payload": {"orderType": "LIMIT", "price": 10.0}},
        gate=gate,
    )
    assert result == "gate_closed"
