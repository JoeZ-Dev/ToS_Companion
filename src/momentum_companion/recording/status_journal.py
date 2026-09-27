from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, TextIO

from momentum_companion.recording.provenance import (
    DERIVED_JOURNAL_SCHEMA_VERSION,
    deterministic_fingerprint,
)

STATUS_JOURNAL_FILENAME = "security_status_events.jsonl"


def _optional_provider_value(fields: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in fields:
            return fields[key]
    return None


class SecurityStatusJournal:
    """Persist explicit provider security-status transitions from raw deltas."""

    def __init__(self, session_dir: Path, *, source_mode: str = "live") -> None:
        self.session_dir = Path(session_dir)
        self.session_id = self.session_dir.name
        self.source_mode = source_mode
        self.path = self.session_dir / STATUS_JOURNAL_FILENAME
        self._handle: TextIO | None = None
        self._last_values: dict[str, tuple[Any, Any, Any]] = {}
        self.count = 0

    def append_payload(
        self,
        payload: Mapping[str, Any],
        *,
        active_symbols: Iterable[str],
        observed_at_utc: str,
    ) -> int:
        active = {str(symbol).strip().upper() for symbol in active_symbols}
        appended = 0
        for message in _stream_messages(payload):
            if message.get("service") != "LEVELONE_EQUITIES":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for fields in content:
                if not isinstance(fields, Mapping) or "32" not in fields:
                    continue
                symbol = str(fields.get("key") or fields.get("0") or "").strip().upper()
                if symbol not in active:
                    continue
                status = fields.get("32")
                reason = _optional_provider_value(
                    fields, "statusReason", "securityStatusReason", "reason"
                )
                reason_code = _optional_provider_value(
                    fields, "statusReasonCode", "reasonCode", "statusCode"
                )
                transition = (status, reason, reason_code)
                if self._last_values.get(symbol) == transition:
                    continue
                provider_ts_ms = _optional_int(message.get("timestamp"))
                identity = {
                    "session_id": self.session_id,
                    "symbol": symbol,
                    "provider_ts_ms": provider_ts_ms,
                    "provider_status": status,
                    "provider_reason": reason,
                    "provider_reason_code": reason_code,
                    "source_mode": self.source_mode,
                }
                event = {
                    "schema_version": DERIVED_JOURNAL_SCHEMA_VERSION,
                    "kind": "security_status_event",
                    "event_id": deterministic_fingerprint(identity),
                    "session_id": self.session_id,
                    "symbol": symbol,
                    "provider_status": status,
                    "provider_reason": reason,
                    "provider_reason_code": reason_code,
                    "provider_ts_ms": provider_ts_ms,
                    "provider_timestamp_source": "message.timestamp",
                    "observed_at_utc": observed_at_utc,
                    "source_mode": self.source_mode,
                    "provider_fields": {
                        "32": status,
                    },
                }
                if self._handle is None:
                    self._handle = self.path.open("a", encoding="utf-8")
                self._handle.write(json.dumps(event, separators=(",", ":")) + "\n")
                self._handle.flush()
                self._last_values[symbol] = transition
                self.count += 1
                appended += 1
        return appended

    def close(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None


def _stream_messages(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    messages: list[Mapping[str, Any]] = []
    if payload.get("service"):
        messages.append(payload)
    data = payload.get("data")
    if isinstance(data, list):
        messages.extend(item for item in data if isinstance(item, Mapping))
    return messages


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
