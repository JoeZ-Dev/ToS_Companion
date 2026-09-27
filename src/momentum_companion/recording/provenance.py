from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from momentum_companion.data.bar_aggregator import WINDOW_SEC
from momentum_companion.setup_engine.pattern_engine import PatternEngine
from momentum_companion.setup_engine.patterns import build_default_pattern_engine


MANIFEST_SCHEMA_VERSION = 2
MARKET_EVENT_SCHEMA_VERSION = 1
DERIVED_JOURNAL_SCHEMA_VERSION = 1
FROZEN_DETECTOR_REVISIONS = {
    "MICRO_PULLBACK": "33181b1ecf1bcce446a25ca136688342262262ea",
}
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported provenance value: {type(value).__name__}")


def deterministic_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def application_git_state() -> tuple[str | None, bool | None]:
    configured = str(os.getenv("TOS_COMPANION_GIT_REVISION") or "").strip().lower()
    if configured:
        dirty_value = str(
            os.getenv("TOS_COMPANION_GIT_WORKTREE_DIRTY") or ""
        ).strip().lower()
        dirty = {
            "0": False,
            "false": False,
            "1": True,
            "true": True,
        }.get(dirty_value)
        return (configured if _GIT_SHA_RE.fullmatch(configured) else None, dirty)

    root = _repository_root()
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip().lower()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    return (revision if _GIT_SHA_RE.fullmatch(revision) else None, dirty)


def application_version() -> str | None:
    try:
        return metadata.version("momentum-companion")
    except metadata.PackageNotFoundError:
        return None


def detector_inventory(engine: PatternEngine) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for detector in engine.detectors:
        name = str(detector.name)
        config = _json_value(getattr(detector, "config", None))
        inventory.append(
            {
                "name": name,
                "config": config,
                "config_fingerprint": deterministic_fingerprint(config),
                "semantic_revision": FROZEN_DETECTOR_REVISIONS.get(name),
            }
        )
    return inventory


def build_recording_provenance(
    *,
    engine: PatternEngine | None = None,
    git_revision: str | None = None,
    git_worktree_dirty: bool | None = None,
    app_version: str | None = None,
) -> dict[str, Any]:
    if git_revision is None and git_worktree_dirty is None:
        git_revision, git_worktree_dirty = application_git_state()
    if app_version is None:
        app_version = application_version()

    inventory = detector_inventory(engine or build_default_pattern_engine())
    detector_fingerprint_input = [
        {
            "name": item["name"],
            "config_fingerprint": item["config_fingerprint"],
            "semantic_revision": item["semantic_revision"],
        }
        for item in inventory
    ]
    return {
        "application": {
            "git_revision": git_revision,
            "git_worktree_dirty": git_worktree_dirty,
            "version": app_version,
        },
        "detectors": {
            "enabled": inventory,
            "inventory_fingerprint": deterministic_fingerprint(
                detector_fingerprint_input
            ),
        },
        "schemas": {
            "manifest": MANIFEST_SCHEMA_VERSION,
            "market_event": MARKET_EVENT_SCHEMA_VERSION,
            "derived_journal": DERIVED_JOURNAL_SCHEMA_VERSION,
        },
        "pattern_evaluation": {
            "bar_cadence_seconds": WINDOW_SEC,
        },
        "session": {
            "timezone": "America/New_York",
            "premarket_start_et": "04:00:00",
            "regular_market_open_et": "09:30:00",
            "regular_market_close_et": "16:00:00",
            "after_hours_end_et": "20:00:00",
            "recording_cutoff_et": "15:00:00",
        },
        "source_mode": "live",
    }


def normalize_manifest_provenance(manifest: Mapping[str, Any]) -> dict[str, Any]:
    unknown = {
        "application": {
            "git_revision": None,
            "git_worktree_dirty": None,
            "version": None,
        },
        "detectors": {
            "enabled": None,
            "inventory_fingerprint": None,
        },
        "schemas": {
            "manifest": manifest.get("schema_version"),
            "market_event": None,
            "derived_journal": None,
        },
        "pattern_evaluation": {
            "bar_cadence_seconds": None,
        },
        "session": {
            "timezone": None,
            "premarket_start_et": None,
            "regular_market_open_et": None,
            "regular_market_close_et": None,
            "after_hours_end_et": None,
            "recording_cutoff_et": manifest.get("scheduled_cutoff_et"),
        },
        "source_mode": None,
    }
    value = manifest.get("provenance")
    if not isinstance(value, Mapping):
        return unknown

    normalized = _json_value(value)
    for section, defaults in unknown.items():
        if isinstance(defaults, dict):
            current = normalized.get(section)
            if not isinstance(current, dict):
                normalized[section] = defaults
                continue
            for key, default in defaults.items():
                current.setdefault(key, default)
        else:
            normalized.setdefault(section, defaults)
    return normalized
