from momentum_companion.execution.trade_executor import TradeExecutor
from momentum_companion.execution.emm_engine import EMMEngine
from momentum_companion.triggers.synthetic import SyntheticTriggerEngine
from momentum_companion.journal.writer import JournalWriter
from momentum_companion.data.schema import init_db
from momentum_companion.state.app_state import AppStateStore


class DummyRest:
    def get_orders(self, account_id):
        return []

    def place_order(self, account_id, payload):
        return "order123"


def test_trade_executor_journals_normal_order(tmp_path):
    db_path = tmp_path / "data.db"
    init_db(db_path)
    journal = JournalWriter(db_path)
    rest = DummyRest()
    emm = EMMEngine(rest)
    trig = SyntheticTriggerEngine(None)
    exec = TradeExecutor(rest, emm, trig, journal)
    order_id = exec.submit_order(
        {
            "account_id": "acc1",
            "order_payload": {"orderType": "LIMIT", "price": 10.0},
            "session_mode": "NORMAL",
            "side": "BUY",
            "qty": 1,
            "ts_utc": "2026-02-08T12:00:00Z",
            "symbol": "AAPL",
        }
    )
    assert order_id == "order123"
