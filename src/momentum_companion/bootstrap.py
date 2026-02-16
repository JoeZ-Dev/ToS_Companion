from __future__ import annotations

from pathlib import Path

from momentum_companion.data.schema import init_db
from momentum_companion.state.app_state import AppStateStore
from momentum_companion.journal.writer import JournalWriter
from momentum_companion.utils.paths import instance_db_path, oauth_lock_path, log_path
from momentum_companion.utils.logging import setup_logging


def bootstrap(instance_id: str) -> tuple[Path, AppStateStore, JournalWriter]:
    """Initialize DB, app_state, and journal writer per specs."""
    db_path = instance_db_path(instance_id)
    init_db(db_path)
    setup_logging(str(log_path()))
    app_state = AppStateStore(str(db_path))
    journal = JournalWriter(db_path)
    return db_path, app_state, journal
