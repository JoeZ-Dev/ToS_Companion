from momentum_companion.llm.service import LLMService
from momentum_companion.llm.coach import LLMCoach
from momentum_companion.journal.writer import JournalWriter
from momentum_companion.data.schema import init_db


class BadCoach(LLMCoach):
    def run(self, snapshot_payload, context):
        return {"validity": "VALID_FOR_TRADING", "reason_codes": ["BAD_CODE"]}

    def validate_response(self, resp):
        return True


def test_llm_invalid_output_journal(tmp_path):
    db_path = tmp_path / "data.db"
    init_db(db_path)
    journal = JournalWriter(db_path)
    svc = LLMService(BadCoach(), client=None, journal=journal)
    resp = svc.evaluate(
        {"status": "ok", "data_quality": "ok", "as_of_ts_ms": 1, "symbol": "AAPL", "market_state": "normal"},
        "SEAMLESS",
        {"bid": 1, "ask": 2, "last": 1.5, "volume": 100},
    )
    assert resp["validity"] == "NOT_VALID_FOR_TRADING"
