from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from momentum_companion.recording.backfill import load_backfill_candles
from momentum_companion.recording.provenance import normalize_manifest_provenance


class RecordingCatalog:
    """Read-only discovery and loading for persisted market-day recordings."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def list_sessions(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        sessions: list[dict[str, Any]] = []
        for manifest_path in sorted(self.root.glob("*/manifest.json"), reverse=True):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("kind") != "market_day_recording":
                continue
            sessions.append(
                {
                    "session_id": manifest_path.parent.name,
                    "started_at_et": manifest.get("started_at_et"),
                    "ended_at_et": manifest.get("ended_at_et"),
                    "symbols": [
                        str(symbol).strip().upper()
                        for symbol in manifest.get("symbols") or []
                        if str(symbol).strip()
                    ],
                    "counts": manifest.get("counts") or {},
                    "stop_reason": manifest.get("stop_reason"),
                    "historical_backfill": manifest.get("historical_backfill") or {},
                    "provenance": normalize_manifest_provenance(manifest),
                }
            )
        return sessions

    def load_manifest(self, session_id: str) -> dict[str, Any]:
        session_dir = self._session_dir(session_id)
        manifest_path = session_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"unknown replay session: {session_id}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid replay manifest: {session_id}") from exc
        if manifest.get("kind") != "market_day_recording":
            raise ValueError(f"invalid replay session: {session_id}")
        manifest["provenance"] = normalize_manifest_provenance(manifest)
        return manifest

    def load_events(self, session_id: str, symbol: str) -> list[dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        session_dir = self._session_dir(session_id)
        manifest = self.load_manifest(session_id)
        symbols = {
            str(value).strip().upper()
            for value in manifest.get("symbols") or []
            if str(value).strip()
        }
        if normalized not in symbols:
            raise ValueError(f"{normalized} is not recorded in session {session_id}")

        event_path = session_dir / f"{normalized}.jsonl"
        events: list[tuple[int, dict[str, Any]]] = []
        try:
            with event_path.open("r", encoding="utf-8") as handle:
                for index, line in enumerate(handle):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = record.get("kind")
                    if str(record.get("symbol") or "").strip().upper() != normalized:
                        continue
                    if record.get("stream_ts_ms") is None:
                        continue
                    if kind == "market_event":
                        if record.get("service") != "LEVELONE_EQUITIES":
                            continue
                        if not isinstance(record.get("raw"), dict):
                            continue
                    elif kind == "historical_candle":
                        if not isinstance(record.get("candle"), dict):
                            continue
                    else:
                        continue
                    events.append((index, record))
        except FileNotFoundError as exc:
            raise ValueError(f"recording file missing for {normalized}") from exc

        events.sort(key=lambda item: (int(item[1]["stream_ts_ms"]), item[0]))
        return [record for _, record in events]

    def load_history(
        self,
        session_id: str,
        symbol: str,
        *,
        through_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        session_dir = self._session_dir(session_id)
        manifest = self.load_manifest(session_id)
        symbols = {
            str(value).strip().upper()
            for value in manifest.get("symbols") or []
            if str(value).strip()
        }
        if normalized not in symbols:
            raise ValueError(f"{normalized} is not recorded in session {session_id}")
        return load_backfill_candles(
            session_dir,
            normalized,
            through_ms=through_ms,
        )

    def load_pattern_events(
        self, session_id: str, *, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        session_dir = self._session_dir(session_id)
        self.load_manifest(session_id)
        normalized = str(symbol or "").strip().upper() or None
        path = session_dir / "pattern_events.jsonl"
        events: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("kind") != "pattern_event":
                        continue
                    event_symbol = str(event.get("symbol") or "").strip().upper()
                    if normalized is not None and event_symbol != normalized:
                        continue
                    events.append(event)
        except FileNotFoundError:
            return []
        return sorted(
            events,
            key=lambda event: (
                int(event.get("observation_ts_ms") or 0),
                str(event.get("event_id") or ""),
            ),
        )

    def _session_dir(self, session_id: str) -> Path:
        value = str(session_id or "").strip()
        if not value or Path(value).name != value or "/" in value or "\\" in value:
            raise ValueError("invalid session_id")
        session_dir = self.root / value
        try:
            resolved_root = self.root.resolve()
            resolved_session = session_dir.resolve()
            resolved_session.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise ValueError("invalid session_id") from exc
        return session_dir
