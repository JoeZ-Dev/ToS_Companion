from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4


class ReviewAnnotationStore:
    """Append-only model/human labels kept outside immutable recordings."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "annotations.jsonl"
        self._lock = threading.RLock()

    def add(self, annotation: dict[str, Any]) -> dict[str, Any]:
        required = ("session_id", "symbol", "setup_type", "trigger_ms", "valid_at_time")
        missing = [key for key in required if annotation.get(key) in (None, "")]
        if missing:
            raise ValueError("missing annotation fields: " + ", ".join(missing))

        item = dict(annotation)
        item["annotation_id"] = str(item.get("annotation_id") or uuid4())
        item["symbol"] = str(item["symbol"]).strip().upper()
        item["trigger_ms"] = int(item["trigger_ms"])
        if item.get("setup_start_ms") is not None:
            item["setup_start_ms"] = int(item["setup_start_ms"])
        item.setdefault("review_pass", "discovery")
        item.setdefault("source", "chatgpt")
        item.setdefault("outcome", "unknown")
        item.setdefault("confidence", None)
        item.setdefault("evidence", {})
        item.setdefault("notes", "")
        item["created_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, separators=(",", ":"), default=str) + "\n")
        return item

    def list(
        self,
        *,
        session_id: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        normalized_symbol = str(symbol or "").strip().upper() or None
        result: list[dict[str, Any]] = []
        with self._lock:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if session_id is not None and item.get("session_id") != session_id:
                        continue
                    if normalized_symbol is not None and str(item.get("symbol") or "").upper() != normalized_symbol:
                        continue
                    result.append(item)
        return result
