from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from momentum_companion.evaluation.corpus_registry import (
    DEVELOPMENT_SESSIONS,
    EVALUATION_BASELINE_REVISION,
    MICRO_PULLBACK_FROZEN_DETECTOR_REVISION,
)

CLASSIFICATIONS = frozenset({"unclassified", "development", "holdout"})
SCHEMA_VERSION = 1
UTC = timezone.utc


class CorpusClassificationRegistryError(RuntimeError):
    pass


class CorpusClassificationStore:
    """Persist prospective corpus reservations outside immutable recordings."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def get(self, session_id: str) -> dict[str, Any]:
        normalized = _session_id(session_id)
        with self._lock:
            item = self._read()["sessions"].get(normalized)
        if isinstance(item, dict):
            return {"session_id": normalized, "source": "persisted", **item}
        if normalized in DEVELOPMENT_SESSIONS:
            return {
                "session_id": normalized,
                "classification": "development",
                "classified_at_utc": None,
                "note": "Fixed historical development corpus.",
                "source": "repository_baseline",
                "history": [],
            }
        return {
            "session_id": normalized,
            "classification": "unclassified",
            "classified_at_utc": None,
            "note": None,
            "source": "default",
            "history": [],
        }

    def classify(
        self,
        session_id: str,
        classification: str,
        *,
        note: str | None = None,
        confirm_holdout_relabel: bool = False,
    ) -> dict[str, Any]:
        normalized = _session_id(session_id)
        target = str(classification or "").strip().lower()
        if target not in CLASSIFICATIONS:
            raise ValueError("classification must be unclassified, development, or holdout")
        if normalized in DEVELOPMENT_SESSIONS and target != "development":
            raise ValueError("fixed development sessions cannot be reclassified")

        with self._lock:
            payload = self._read()
            current = self.get(normalized)
            previous = str(current["classification"])
            if previous == target:
                return current
            if previous == "holdout" and not confirm_holdout_relabel:
                raise ValueError(
                    "relabeling a holdout requires confirm_holdout_relabel=true"
                )
            now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            history = list(current.get("history") or [])
            history.append(
                {
                    "from": previous,
                    "to": target,
                    "changed_at_utc": now,
                    "note": str(note).strip() if note is not None else None,
                    "holdout_relabel_confirmed": bool(
                        previous == "holdout" and confirm_holdout_relabel
                    ),
                }
            )
            item = {
                "classification": target,
                "classified_at_utc": now,
                "note": str(note).strip() if note is not None else None,
                "history": history,
            }
            payload["sessions"][normalized] = item
            self._write(payload)
            return {"session_id": normalized, "source": "persisted", **item}

    def list(self, session_ids: list[str] | None = None) -> list[dict[str, Any]]:
        if session_ids is None:
            with self._lock:
                session_ids = sorted(
                    set(DEVELOPMENT_SESSIONS) | set(self._read()["sessions"])
                )
        return [self.get(session_id) for session_id in session_ids]

    def metadata_for(self, session_id: str, detector_type: str | None) -> dict[str, Any]:
        classification = self.get(session_id)
        return {
            "corpus": classification["classification"],
            "classified_at_utc": classification["classified_at_utc"],
            "classification_source": classification["source"],
            "detector_revision": (
                MICRO_PULLBACK_FROZEN_DETECTOR_REVISION
                if detector_type == "MICRO_PULLBACK"
                else None
            ),
            "evaluation_baseline_revision": EVALUATION_BASELINE_REVISION,
        }

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": SCHEMA_VERSION, "sessions": {}}
        except json.JSONDecodeError as exc:
            raise CorpusClassificationRegistryError(
                "invalid corpus classification registry"
            ) from exc
        sessions = value.get("sessions")
        if not isinstance(sessions, dict):
            raise CorpusClassificationRegistryError(
                "invalid corpus classification registry"
            )
        return {"schema_version": SCHEMA_VERSION, "sessions": sessions}

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)


def _session_id(value: str) -> str:
    normalized = str(value or "").strip()
    if (
        not normalized
        or Path(normalized).name != normalized
        or "/" in normalized
        or "\\" in normalized
    ):
        raise ValueError("invalid session_id")
    return normalized
