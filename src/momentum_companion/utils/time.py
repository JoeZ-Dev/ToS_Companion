from __future__ import annotations

from datetime import datetime, timezone


def utc_now_str() -> str:
    """UTC ISO8601 with Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
