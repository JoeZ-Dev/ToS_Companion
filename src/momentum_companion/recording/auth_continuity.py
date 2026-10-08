from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuthorizationContinuityJournal:
    """Outcome-blind append-only authorization outage/recovery evidence."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def append(self, event: str, *, recording_active: bool) -> dict[str, Any]:
        if event not in {"authorization_outage", "authorization_recovered"}:
            raise ValueError("invalid authorization continuity event")
        row = {
            "kind": "authorization_continuity",
            "event": event,
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "recording_active": bool(recording_active),
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return row

    def read(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") == "authorization_continuity":
                rows.append(row)
        return rows
