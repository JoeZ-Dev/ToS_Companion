from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Iterable, List, Optional

from momentum_companion.journal.contracts import JournalEvent
from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


class JournalWriter:
    """Append-only journal writer with verification_degraded semantics (§7.4, §14)."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def append_event(self, event: JournalEvent) -> None:
        """Append a journal event and fsync."""
        if "event_id" not in event:
            event["event_id"] = str(uuid.uuid4())
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO trade_journal (
                    event_id, ts_utc, symbol, event_type, session_mode, connection_state,
                    side, qty, qty_filled, order_type, limit_price, stop_price, broker_order_id,
                    emm_active, emm_ref_price, emm_bound_price, emm_attempt_n, notes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("event_id"),
                    event.get("ts_utc"),
                    event.get("symbol"),
                    event.get("event_type"),
                    event.get("session_mode"),
                    event.get("connection_state"),
                    event.get("side"),
                    event.get("qty"),
                    event.get("qty_filled"),
                    event.get("order_type"),
                    event.get("limit_price"),
                    event.get("stop_price"),
                    event.get("broker_order_id"),
                    event.get("emm_active", 0),
                    event.get("emm_ref_price"),
                    event.get("emm_bound_price"),
                    event.get("emm_attempt_n"),
                    event.get("notes_json"),
                ),
            )
            conn.commit()

    def export_csv(self, dest_path: Path) -> None:
        """Export all journal events to CSV."""
        rows = self._fetch_all()
        import csv

        with open(dest_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "event_id",
                    "ts_utc",
                    "symbol",
                    "event_type",
                    "session_mode",
                    "connection_state",
                    "side",
                    "qty",
                    "qty_filled",
                    "order_type",
                    "limit_price",
                    "stop_price",
                    "broker_order_id",
                    "emm_active",
                    "emm_ref_price",
                    "emm_bound_price",
                    "emm_attempt_n",
                    "notes_json",
                ]
            )
            writer.writerows(rows)

    def export_json(self, dest_path: Path) -> None:
        """Export all journal events to JSON array."""
        rows = self._fetch_all()
        keys = [
            "event_id",
            "ts_utc",
            "symbol",
            "event_type",
            "session_mode",
            "connection_state",
            "side",
            "qty",
            "qty_filled",
            "order_type",
            "limit_price",
            "stop_price",
            "broker_order_id",
            "emm_active",
            "emm_ref_price",
            "emm_bound_price",
            "emm_attempt_n",
            "notes_json",
        ]
        dicts = [dict(zip(keys, row)) for row in rows]
        with open(dest_path, "w", encoding="utf-8") as f:
            json.dump(dicts, f, indent=2)

    def _fetch_all(self) -> List[tuple]:
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                """
                SELECT event_id, ts_utc, symbol, event_type, session_mode, connection_state,
                       side, qty, qty_filled, order_type, limit_price, stop_price, broker_order_id,
                       emm_active, emm_ref_price, emm_bound_price, emm_attempt_n, notes_json
                FROM trade_journal
                ORDER BY ts_utc ASC
                """
            )
            return cur.fetchall()
