from momentum_companion.execution.trade_executor import TradeExecutor
from momentum_companion.execution.emm_engine import EMMEngine
from momentum_companion.triggers.synthetic import SyntheticTriggerEngine
from momentum_companion.journal.writer import JournalWriter
from momentum_companion.data.schema import init_db
from momentum_companion.gates import TradingGateState


class DummyRest:
    def place_order(self, *args, **kwargs):
        return "oid"

    def replace_order(self, *args, **kwargs):
        return "oid"

    def cancel_order(self, *args, **kwargs):
        return None


def test_gate_closed_blocks_submit(tmp_path):
    db_path = tmp_path / "data.db"
    init_db(db_path)
    journal = JournalWriter(db_path)
    rest = DummyRest()
    emm = EMMEngine(rest)
    trig = SyntheticTriggerEngine(None)
    exec = TradeExecutor(rest, emm, trig, journal)
    gate = TradingGateState(auth_ok=False, stream_connected=False, quote_fresh=False, journal_healthy=False, reconciliation_complete=False)
    result = exec.submit_order({"symbol": "AAPL"}, gate=gate)
    assert result == "gate_closed"
