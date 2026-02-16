from __future__ import annotations

import sqlite3
from typing import Any, Optional


class AppStateStore:
    """Handles app_state table reads/writes and persistence toggles (§7.2)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def get(self, key: str) -> Optional[str]:
        """Retrieve a stored value."""
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("SELECT value FROM app_state WHERE key=?", (key,))
            row = cur.fetchone()
            return row[0] if row else None

    def set(self, key: str, value: Any) -> None:
        """Persist a value."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO app_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            conn.commit()
