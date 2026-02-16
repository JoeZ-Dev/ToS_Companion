from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    last_selected_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    is_extended INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'schwab',
    PRIMARY KEY (symbol, timeframe, ts_utc)
);

CREATE INDEX IF NOT EXISTS idx_bars_symbol_timeframe_ts
    ON bars(symbol, timeframe, ts_utc);

CREATE TABLE IF NOT EXISTS market_profile (
    symbol TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    PRIMARY KEY (symbol, created_at_utc)
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_journal (
    event_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    event_type TEXT NOT NULL,
    session_mode TEXT NOT NULL,
    connection_state TEXT NOT NULL,
    side TEXT,
    qty REAL,
    qty_filled REAL,
    order_type TEXT,
    limit_price REAL,
    stop_price REAL,
    broker_order_id TEXT,
    emm_active INTEGER NOT NULL DEFAULT 0,
    emm_ref_price REAL,
    emm_bound_price REAL,
    emm_attempt_n INTEGER,
    notes_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_trade_journal_ts
    ON trade_journal(ts_utc);

CREATE INDEX IF NOT EXISTS idx_trade_journal_symbol_ts
    ON trade_journal(symbol, ts_utc);
"""


def init_db(db_path: Path) -> None:
    """Initialize schema_version=1 and tables per specs.md §7.2."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(DDL)
        if _schema_version_missing(conn):
            conn.execute(
                "INSERT INTO schema_version (version, applied_at_utc) VALUES (?, datetime('now'))",
                (1,),
            )
        conn.commit()


def _schema_version_missing(conn: sqlite3.Connection) -> bool:
    try:
        cur = conn.execute("SELECT COUNT(1) FROM schema_version")
        row = cur.fetchone()
        return row is None or row[0] == 0
    except sqlite3.DatabaseError:
        return True
