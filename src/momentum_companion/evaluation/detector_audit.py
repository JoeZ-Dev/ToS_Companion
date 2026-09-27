from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Callable

from momentum_companion.replay.engine import ReplayEngine
from momentum_companion.review.annotations import ReviewAnnotationStore


DETECTOR_ALIASES: dict[str, str] = {
    "ascending_triangle": "ASCENDING_TRIANGLE",
    "micro_pullback": "MICRO_PULLBACK",
    "micro_pullback_breakout": "MICRO_PULLBACK",
}

TRIGGER_STATES: dict[str, set[str]] = {
    "ASCENDING_TRIANGLE": {"BREAKOUT"},
    "MICRO_PULLBACK": {"CONTINUATION"},
}

INSTANCE_START_TOLERANCE_MS: dict[str, int] = {
    "ASCENDING_TRIANGLE": 5 * 60 * 1000,
    "MICRO_PULLBACK": 2 * 60 * 1000,
}


class DetectorAnnotationEvaluator:
    """Compare replay detector observations with verified review annotations.

    The evaluator is descriptive. It never changes detector configuration or
    annotations and does not treat model labels as strategy truth.
    """

    def __init__(
        self,
        *,
        recordings_root: Path,
        annotation_store: ReviewAnnotationStore,
        replay_factory: Callable[[], ReplayEngine] | None = None,
    ) -> None:
        self.recordings_root = Path(recordings_root)
        self.annotation_store = annotation_store
        self._replay_factory = replay_factory or (
            lambda: ReplayEngine(recordings_root=self.recordings_root)
        )

    def audit(
        self,
        *,
        session_id: str | None = None,
        symbol: str | None = None,
        default_lookback_ms: int = 5 * 60 * 1000,
        post_trigger_ms: int = 2 * 60 * 1000,
    ) -> dict[str, Any]:
        if default_lookback_ms <= 0:
            raise ValueError("default_lookback_ms must be positive")
        if post_trigger_ms < 0:
            raise ValueError("post_trigger_ms must be non-negative")

        annotations = [
            item
            for item in self.annotation_store.list(session_id=session_id, symbol=symbol)
            if str(item.get("review_pass") or "").lower() == "verification"
        ]
        annotations.sort(
            key=lambda item: (
                str(item.get("session_id") or ""),
                str(item.get("symbol") or ""),
                int(item.get("trigger_ms") or 0),
                str(item.get("annotation_id") or ""),
            )
        )

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for annotation in annotations:
            grouped[
                (
                    str(annotation.get("session_id") or ""),
                    str(annotation.get("symbol") or "").upper(),
                )
            ].append(annotation)

        timeline_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        replay_errors: list[dict[str, str]] = []
        results: list[dict[str, Any]] = []

        for key, group in grouped.items():
            session, normalized_symbol = key
            if not session or not normalized_symbol:
                continue
            try:
                engine = self._replay_factory()
                loaded = engine.load(session, normalized_symbol)
                engine.seek(int(loaded.get("total_events") or 0))
                timeline = [dict(item) for item in engine.pattern_timeline]
                timeline_cache[key] = timeline
            except (ValueError, RuntimeError, OSError) as exc:
                replay_errors.append(
                    {
                        "session_id": session,
                        "symbol": normalized_symbol,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                timeline = []

            for annotation in group:
                results.append(
                    self.compare_annotation(
                        annotation,
                        timeline,
                        default_lookback_ms=default_lookback_ms,
                        post_trigger_ms=post_trigger_ms,
                    )
                )

        return {
            "schema_version": 1,
            "purpose": "detector_vs_verified_annotation_audit",
            "configuration": {
                "default_lookback_ms": default_lookback_ms,
                "post_trigger_ms": post_trigger_ms,
                "trigger_states": {
                    key: sorted(value) for key, value in TRIGGER_STATES.items()
                },
                "aliases": dict(DETECTOR_ALIASES),
            },
            "summary": self._summarize(results),
            "results": results,
            "replay_errors": replay_errors,
        }

    @staticmethod
    def compare_annotation(
        annotation: dict[str, Any],
        timeline: list[dict[str, Any]],
        *,
        default_lookback_ms: int = 5 * 60 * 1000,
        post_trigger_ms: int = 2 * 60 * 1000,
    ) -> dict[str, Any]:
        setup_type = str(annotation.get("setup_type") or "").strip().lower()
        detector_type = DETECTOR_ALIASES.get(setup_type)
        trigger_ms = int(annotation.get("trigger_ms") or 0)
        setup_start = annotation.get("setup_start_ms")
        window_start_ms = (
            int(setup_start)
            if setup_start is not None
            else trigger_ms - int(default_lookback_ms)
        )
        window_end_ms = trigger_ms + int(post_trigger_ms)
        valid_at_time = bool(annotation.get("valid_at_time"))

        base = {
            "annotation_id": annotation.get("annotation_id"),
            "session_id": annotation.get("session_id"),
            "symbol": str(annotation.get("symbol") or "").upper(),
            "setup_type": setup_type,
            "detector_type": detector_type,
            "valid_at_time": valid_at_time,
            "outcome": annotation.get("outcome"),
            "confidence": annotation.get("confidence"),
            "setup_start_ms": setup_start,
            "trigger_ms": trigger_ms,
            "comparison_window": {
                "start_ms": window_start_ms,
                "end_ms": window_end_ms,
            },
        }

        if detector_type is None:
            return {
                **base,
                "supported_by_current_detector_registry": False,
                "matching": {
                    "status": "unsupported_setup_type",
                    "basis": None,
                    "pattern_id": None,
                    "instance_started_ms": None,
                    "start_distance_ms": None,
                    "candidate_instance_count": 0,
                },
                "structure_detected": False,
                "structure_detected_by_trigger": False,
                "trigger_detected": False,
                "fired_by_annotated_trigger": False,
                "false_positive_on_rejected_candidate": False,
                "first_structure_ms": None,
                "first_structure_by_trigger_ms": None,
                "first_trigger_state_ms": None,
                "trigger_latency_ms": None,
                "state_at_annotated_trigger": None,
                "nearby_observations": [],
            }

        candidate_observations: list[dict[str, Any]] = []
        for item in timeline:
            pattern = item.get("pattern") or {}
            if str(pattern.get("pattern_type") or "").upper() != detector_type:
                continue
            updated_at = pattern.get("updated_at")
            if updated_at is None:
                continue
            updated_ms = int(updated_at) * 1000
            if window_start_ms <= updated_ms <= window_end_ms:
                candidate_observations.append(
                    {
                        "updated_ms": updated_ms,
                        "started_ms": (
                            int(pattern["started_at"]) * 1000
                            if pattern.get("started_at") is not None
                            else None
                        ),
                        "state": str(pattern.get("state") or ""),
                        "pattern_id": pattern.get("id"),
                        "evidence": dict(pattern.get("evidence") or {}),
                    }
                )
        candidate_observations.sort(key=lambda item: item["updated_ms"])

        nearby, match = DetectorAnnotationEvaluator._match_pattern_instance(
            candidate_observations,
            detector_type=detector_type,
            trigger_ms=trigger_ms,
            setup_start_ms=(int(setup_start) if setup_start is not None else None),
        )

        trigger_states = TRIGGER_STATES.get(detector_type, set())
        trigger_observations = [
            item for item in nearby if item["state"] in trigger_states
        ]
        by_trigger = [
            item for item in nearby if item["updated_ms"] <= trigger_ms
        ]
        trigger_by_trigger = [
            item for item in trigger_observations if item["updated_ms"] <= trigger_ms
        ]
        first_structure = nearby[0] if nearby else None
        first_structure_by_trigger = by_trigger[0] if by_trigger else None
        first_trigger = trigger_observations[0] if trigger_observations else None
        state_at_trigger = by_trigger[-1]["state"] if by_trigger else None

        return {
            **base,
            "supported_by_current_detector_registry": True,
            "matching": match,
            "structure_detected": bool(nearby),
            "structure_detected_by_trigger": bool(by_trigger),
            "trigger_detected": bool(trigger_observations),
            "fired_by_annotated_trigger": bool(trigger_by_trigger),
            "false_positive_on_rejected_candidate": (
                (not valid_at_time) and bool(trigger_by_trigger)
            ),
            "first_structure_ms": (
                first_structure["updated_ms"] if first_structure else None
            ),
            "first_structure_by_trigger_ms": (
                first_structure_by_trigger["updated_ms"]
                if first_structure_by_trigger else None
            ),
            "first_trigger_state_ms": (
                first_trigger["updated_ms"] if first_trigger else None
            ),
            "trigger_latency_ms": (
                first_trigger["updated_ms"] - trigger_ms
                if first_trigger is not None
                else None
            ),
            "state_at_annotated_trigger": state_at_trigger,
            "nearby_observations": nearby,
        }

    @staticmethod
    def _match_pattern_instance(
        observations: list[dict[str, Any]],
        *,
        detector_type: str,
        trigger_ms: int,
        setup_start_ms: int | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Select one detector instance before scoring an annotation.

        Pattern detectors can emit repeated observations for multiple formations
        in the same broad comparison window. Matching all observations together
        can incorrectly let an older completed setup satisfy a later annotation.
        """
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in observations:
            pattern_id = str(item.get("pattern_id") or "")
            if pattern_id:
                groups[pattern_id].append(item)

        candidates: list[dict[str, Any]] = []
        for pattern_id, items in groups.items():
            items.sort(key=lambda item: item["updated_ms"])
            starts = [
                int(item["started_ms"])
                for item in items
                if item.get("started_ms") is not None
            ]
            if not starts:
                continue
            started_ms = min(starts)
            before_or_at = [
                item for item in items if int(item["updated_ms"]) <= trigger_ms
            ]
            nearest_distance_ms = min(
                abs(int(item["updated_ms"]) - trigger_ms) for item in items
            )
            candidates.append(
                {
                    "pattern_id": pattern_id,
                    "started_ms": started_ms,
                    "items": items,
                    "has_observation_by_trigger": bool(before_or_at),
                    "last_observation_by_trigger_ms": (
                        int(before_or_at[-1]["updated_ms"]) if before_or_at else None
                    ),
                    "nearest_observation_distance_ms": nearest_distance_ms,
                }
            )

        if not candidates:
            return [], {
                "status": "no_matching_instance",
                "basis": None,
                "pattern_id": None,
                "instance_started_ms": None,
                "start_distance_ms": None,
                "candidate_instance_count": 0,
            }

        tolerance = INSTANCE_START_TOLERANCE_MS.get(
            detector_type, 2 * 60 * 1000
        )

        if setup_start_ms is not None:
            eligible = [
                candidate
                for candidate in candidates
                if abs(candidate["started_ms"] - setup_start_ms) <= tolerance
            ]
            if not eligible:
                return [], {
                    "status": "no_matching_instance",
                    "basis": "setup_start_ms",
                    "pattern_id": None,
                    "instance_started_ms": None,
                    "start_distance_ms": None,
                    "candidate_instance_count": len(candidates),
                    "start_tolerance_ms": tolerance,
                }
            chosen = min(
                eligible,
                key=lambda candidate: (
                    abs(candidate["started_ms"] - setup_start_ms),
                    candidate["nearest_observation_distance_ms"],
                    -candidate["started_ms"],
                ),
            )
            basis = "setup_start_ms"
            start_distance_ms = chosen["started_ms"] - setup_start_ms
        else:
            eligible = [
                candidate
                for candidate in candidates
                if candidate["started_ms"] <= trigger_ms
                and candidate["has_observation_by_trigger"]
            ]
            if eligible:
                # Without a reviewer-supplied setup start, prefer the most
                # recently formed detector instance that actually existed by
                # the annotation trigger. This prevents older completed
                # patterns in the lookback window from being credited to a
                # later candidate.
                chosen = max(
                    eligible,
                    key=lambda candidate: (
                        candidate["started_ms"],
                        candidate["last_observation_by_trigger_ms"] or -1,
                    ),
                )
                basis = "latest_instance_by_trigger"
            else:
                # A detector may first recognize the setup after the annotated
                # trigger. Preserve that as a late structure detection rather
                # than reporting no matching instance. Choose the nearest
                # post-trigger instance so broad-window recall and trigger-time
                # recall remain distinct.
                post_trigger = [
                    candidate
                    for candidate in candidates
                    if candidate["started_ms"] > trigger_ms
                ]
                if not post_trigger:
                    return [], {
                        "status": "no_matching_instance",
                        "basis": "latest_instance_by_trigger",
                        "pattern_id": None,
                        "instance_started_ms": None,
                        "start_distance_ms": None,
                        "candidate_instance_count": len(candidates),
                    }
                chosen = min(
                    post_trigger,
                    key=lambda candidate: (
                        candidate["started_ms"] - trigger_ms,
                        candidate["nearest_observation_distance_ms"],
                    ),
                )
                basis = "nearest_post_trigger_instance"
            start_distance_ms = chosen["started_ms"] - trigger_ms

        matched = [dict(item) for item in chosen["items"]]
        matched.sort(key=lambda item: item["updated_ms"])
        return matched, {
            "status": "matched",
            "basis": basis,
            "pattern_id": chosen["pattern_id"],
            "instance_started_ms": chosen["started_ms"],
            "start_distance_ms": start_distance_ms,
            "candidate_instance_count": len(candidates),
            "start_tolerance_ms": tolerance if setup_start_ms is not None else None,
        }

    @staticmethod
    def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
        supported = [
            item for item in results if item["supported_by_current_detector_registry"]
        ]
        unsupported = [
            item for item in results if not item["supported_by_current_detector_registry"]
        ]
        valid_supported = [item for item in supported if item["valid_at_time"]]
        rejected_supported = [item for item in supported if not item["valid_at_time"]]

        detector_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in supported:
            detector_groups[str(item["detector_type"])].append(item)

        per_detector: dict[str, Any] = {}
        for detector, items in sorted(detector_groups.items()):
            valid = [item for item in items if item["valid_at_time"]]
            rejected = [item for item in items if not item["valid_at_time"]]
            structure_hits = [item for item in valid if item["structure_detected"]]
            structure_hits_by_trigger = [
                item for item in valid if item["structure_detected_by_trigger"]
            ]
            trigger_hits = [item for item in valid if item["trigger_detected"]]
            false_positives = [
                item
                for item in rejected
                if item["false_positive_on_rejected_candidate"]
            ]
            latencies = [
                int(item["trigger_latency_ms"])
                for item in trigger_hits
                if item["trigger_latency_ms"] is not None
            ]
            per_detector[detector] = {
                "verified_valid_labels": len(valid),
                "rejected_labels": len(rejected),
                "structure_detected_valid": len(structure_hits),
                "structure_recall": (
                    len(structure_hits) / len(valid) if valid else None
                ),
                "structure_detected_by_trigger_valid": len(structure_hits_by_trigger),
                "structure_recall_at_trigger": (
                    len(structure_hits_by_trigger) / len(valid) if valid else None
                ),
                "trigger_detected_valid": len(trigger_hits),
                "trigger_recall": len(trigger_hits) / len(valid) if valid else None,
                "missed_valid": len(valid) - len(structure_hits),
                "false_positive_rejected": len(false_positives),
                "false_positive_rate_on_rejected": (
                    len(false_positives) / len(rejected) if rejected else None
                ),
                "median_trigger_latency_ms": median(latencies) if latencies else None,
                "early_trigger_count": sum(1 for value in latencies if value < 0),
                "on_time_trigger_count": sum(1 for value in latencies if value == 0),
                "late_trigger_count": sum(1 for value in latencies if value > 0),
            }

        all_trigger_latencies = [
            int(item["trigger_latency_ms"])
            for item in valid_supported
            if item["trigger_latency_ms"] is not None
        ]
        return {
            "verification_annotations": len(results),
            "supported_annotations": len(supported),
            "unsupported_annotations": len(unsupported),
            "verified_valid_supported": len(valid_supported),
            "rejected_supported": len(rejected_supported),
            "structure_detected_valid": sum(
                1 for item in valid_supported if item["structure_detected"]
            ),
            "structure_detected_by_trigger_valid": sum(
                1
                for item in valid_supported
                if item["structure_detected_by_trigger"]
            ),
            "trigger_detected_valid": sum(
                1 for item in valid_supported if item["trigger_detected"]
            ),
            "false_positive_rejected": sum(
                1
                for item in rejected_supported
                if item["false_positive_on_rejected_candidate"]
            ),
            "no_matching_instance": sum(
                1
                for item in supported
                if (item.get("matching") or {}).get("status") == "no_matching_instance"
            ),
            "median_trigger_latency_ms": (
                median(all_trigger_latencies) if all_trigger_latencies else None
            ),
            "per_detector": per_detector,
            "unsupported_setup_types": sorted(
                {str(item["setup_type"]) for item in unsupported}
            ),
        }
