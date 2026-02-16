from pathlib import Path
import sqlite3

from momentum_companion.journal.writer import JournalWriter
from momentum_companion.data.schema import init_db


def test_journal_append_and_export(tmp_path: Path):
    db_path = tmp_path / "data.db"
    init_db(db_path)
    writer = JournalWriter(db_path)
    writer.append_event(
        {
            "ts_utc": "2026-02-08T12:00:00Z",
            "symbol": "AAPL",
            "event_type": "BROKER_SUBMIT",
            "session_mode": "SEAMLESS",
            "connection_state": "CONNECTED",
            "side": "BUY",
            "qty": 10,
            "order_type": "LIMIT",
            "limit_price": 100.0,
        }
    )
    csv_path = tmp_path / "journal.csv"
    json_path = tmp_path / "journal.json"
    writer.export_csv(csv_path)
    writer.export_json(json_path)

    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("SELECT COUNT(1) FROM trade_journal")
        assert cur.fetchone()[0] == 1
    assert csv_path.exists()
    assert json_path.exists()
