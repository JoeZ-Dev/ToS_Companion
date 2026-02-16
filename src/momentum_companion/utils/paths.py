from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir, user_runtime_dir

APP_NAME = "MomentumTradingCompanion"


def instance_data_dir(instance_id: str) -> Path:
    """Return the per-instance data directory (specs.md §7.1)."""
    return Path(user_data_dir(APP_NAME)) / "instances" / instance_id


def instance_db_path(instance_id: str) -> Path:
    """Return the per-instance SQLite path (specs.md §7.1)."""
    return instance_data_dir(instance_id) / "data.db"


def oauth_lock_path() -> Path:
    """Return the OAuth lock path (specs.md §7.1)."""
    return Path(user_runtime_dir(APP_NAME)) / "oauth.lock"


def log_path() -> Path:
    """Return default log file path (specs.md §14)."""
    return Path(user_data_dir(APP_NAME)) / "app.log"
