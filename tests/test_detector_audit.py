from momentum_companion.evaluation.detector_audit import DetectorAnnotationEvaluator


def _timeline(pattern_type, observations):
    return [
        {
            "bar_ts": updated_ms // 1000,
            "symbol": "TEST",
            "pattern": {
                "id": f"TEST:{pattern_type}:1",
                "pattern_type": pattern_type,
                "state": state,
                "started_at": (updated_ms - 60_000) // 1000,
                "updated_at": updated_ms // 1000,
                "evidence": {"example": True},
            },
        }
        for updated_ms, state in observations
    ]


def test_compare_valid_micro_pullback_reports_structure_and_trigger_latency():
    trigger = 1_800_000_000_000
    annotation = {
        "annotation_id": "a1",
        "session_id": "session",
        "symbol": "TEST",
        "setup_type": "micro_pullback",
        "setup_start_ms": trigger - 90_000,
        "trigger_ms": trigger,
        "valid_at_time": True,
        "outcome": "succeeded",
        "confidence": 0.9,
    }
    timeline = _timeline(
        "MICRO_PULLBACK",
        [
            (trigger - 30_000, "PULLBACK"),
            (trigger - 10_000, "TURNING"),
            (trigger + 10_000, "CONTINUATION"),
        ],
    )

    result = DetectorAnnotationEvaluator.compare_annotation(annotation, timeline)

    assert result["supported_by_current_detector_registry"] is True
    assert result["structure_detected"] is True
    assert result["trigger_detected"] is True
    assert result["fired_by_annotated_trigger"] is False
    assert result["first_structure_ms"] == trigger - 30_000
    assert result["first_trigger_state_ms"] == trigger + 10_000
    assert result["trigger_latency_ms"] == 10_000
    assert result["state_at_annotated_trigger"] == "TURNING"


def test_rejected_candidate_marks_pretrigger_continuation_as_false_positive():
    trigger = 1_800_000_000_000
    annotation = {
        "annotation_id": "a2",
        "session_id": "session",
        "symbol": "TEST",
        "setup_type": "micro_pullback_breakout",
        "trigger_ms": trigger,
        "valid_at_time": False,
        "outcome": "invalid_before_trigger",
    }
    timeline = _timeline(
        "MICRO_PULLBACK",
        [(trigger - 20_000, "CONTINUATION")],
    )

    result = DetectorAnnotationEvaluator.compare_annotation(annotation, timeline)

    assert result["trigger_detected"] is True
    assert result["fired_by_annotated_trigger"] is True
    assert result["false_positive_on_rejected_candidate"] is True
    assert result["trigger_latency_ms"] == -20_000


def test_unsupported_setup_is_explicit_not_counted_as_detector_miss():
    trigger = 1_800_000_000_000
    annotation = {
        "annotation_id": "a3",
        "session_id": "session",
        "symbol": "TEST",
        "setup_type": "local_resistance_breakout",
        "trigger_ms": trigger,
        "valid_at_time": True,
        "outcome": "succeeded",
    }

    result = DetectorAnnotationEvaluator.compare_annotation(annotation, [])

    assert result["supported_by_current_detector_registry"] is False
    assert result["detector_type"] is None
    assert result["trigger_latency_ms"] is None


def test_summary_separates_structure_recall_trigger_recall_and_rejected_false_positives():
    trigger = 1_800_000_000_000
    valid = DetectorAnnotationEvaluator.compare_annotation(
        {
            "annotation_id": "valid",
            "session_id": "session",
            "symbol": "TEST",
            "setup_type": "ascending_triangle",
            "trigger_ms": trigger,
            "valid_at_time": True,
            "outcome": "failed",
        },
        _timeline(
            "ASCENDING_TRIANGLE",
            [
                (trigger - 40_000, "VALID"),
                (trigger + 20_000, "BREAKOUT"),
            ],
        ),
    )
    rejected = DetectorAnnotationEvaluator.compare_annotation(
        {
            "annotation_id": "rejected",
            "session_id": "session",
            "symbol": "TEST",
            "setup_type": "ascending_triangle",
            "trigger_ms": trigger,
            "valid_at_time": False,
            "outcome": "invalid_before_trigger",
        },
        _timeline("ASCENDING_TRIANGLE", [(trigger - 10_000, "BREAKOUT")]),
    )
    unsupported = DetectorAnnotationEvaluator.compare_annotation(
        {
            "annotation_id": "unsupported",
            "session_id": "session",
            "symbol": "TEST",
            "setup_type": "support_reclaim",
            "trigger_ms": trigger,
            "valid_at_time": True,
            "outcome": "succeeded",
        },
        [],
    )

    summary = DetectorAnnotationEvaluator._summarize(
        [valid, rejected, unsupported]
    )

    assert summary["verification_annotations"] == 3
    assert summary["supported_annotations"] == 2
    assert summary["unsupported_annotations"] == 1
    assert summary["structure_detected_valid"] == 1
    assert summary["trigger_detected_valid"] == 1
    assert summary["false_positive_rejected"] == 1
    assert summary["median_trigger_latency_ms"] == 20_000
    assert summary["per_detector"]["ASCENDING_TRIANGLE"]["trigger_recall"] == 1.0
    assert summary["unsupported_setup_types"] == ["support_reclaim"]


def test_instance_matching_does_not_credit_older_completed_pullback():
    trigger = 1_800_000_000_000
    annotation = {
        "annotation_id": "later",
        "session_id": "session",
        "symbol": "TEST",
        "setup_type": "micro_pullback",
        "trigger_ms": trigger,
        "valid_at_time": True,
        "outcome": "succeeded",
    }
    timeline = [
        {
            "bar_ts": (trigger - 300_000) // 1000,
            "symbol": "TEST",
            "pattern": {
                "id": "TEST:MICRO_PULLBACK:old",
                "pattern_type": "MICRO_PULLBACK",
                "state": "CONTINUATION",
                "started_at": (trigger - 360_000) // 1000,
                "updated_at": (trigger - 300_000) // 1000,
                "evidence": {},
            },
        },
        {
            "bar_ts": (trigger - 40_000) // 1000,
            "symbol": "TEST",
            "pattern": {
                "id": "TEST:MICRO_PULLBACK:new",
                "pattern_type": "MICRO_PULLBACK",
                "state": "PULLBACK",
                "started_at": (trigger - 80_000) // 1000,
                "updated_at": (trigger - 40_000) // 1000,
                "evidence": {},
            },
        },
        {
            "bar_ts": (trigger + 20_000) // 1000,
            "symbol": "TEST",
            "pattern": {
                "id": "TEST:MICRO_PULLBACK:new",
                "pattern_type": "MICRO_PULLBACK",
                "state": "CONTINUATION",
                "started_at": (trigger - 80_000) // 1000,
                "updated_at": (trigger + 20_000) // 1000,
                "evidence": {},
            },
        },
    ]

    result = DetectorAnnotationEvaluator.compare_annotation(annotation, timeline)

    assert result["matching"]["pattern_id"] == "TEST:MICRO_PULLBACK:new"
    assert result["first_trigger_state_ms"] == trigger + 20_000
    assert result["trigger_latency_ms"] == 20_000
    assert result["fired_by_annotated_trigger"] is False


def test_setup_start_matching_rejects_unrelated_instance_outside_tolerance():
    trigger = 1_800_000_000_000
    annotation = {
        "annotation_id": "start-aware",
        "session_id": "session",
        "symbol": "TEST",
        "setup_type": "micro_pullback",
        "setup_start_ms": trigger - 60_000,
        "trigger_ms": trigger,
        "valid_at_time": True,
        "outcome": "succeeded",
    }
    timeline = [
        {
            "bar_ts": (trigger - 10_000) // 1000,
            "symbol": "TEST",
            "pattern": {
                "id": "TEST:MICRO_PULLBACK:unrelated",
                "pattern_type": "MICRO_PULLBACK",
                "state": "CONTINUATION",
                "started_at": (trigger - 300_000) // 1000,
                "updated_at": (trigger - 10_000) // 1000,
                "evidence": {},
            },
        }
    ]

    result = DetectorAnnotationEvaluator.compare_annotation(annotation, timeline)

    assert result["matching"]["status"] == "no_matching_instance"
    assert result["matching"]["basis"] == "setup_start_ms"
    assert result["structure_detected"] is False
    assert result["trigger_detected"] is False
    assert result["false_positive_on_rejected_candidate"] is False


def test_structure_recall_at_trigger_does_not_credit_post_trigger_detection():
    trigger = 1_800_000_000_000
    annotation = {
        "annotation_id": "future-structure",
        "session_id": "session",
        "symbol": "TEST",
        "setup_type": "micro_pullback",
        "trigger_ms": trigger,
        "valid_at_time": True,
        "outcome": "succeeded",
    }
    timeline = _timeline(
        "MICRO_PULLBACK",
        [(trigger + 10_000, "PULLBACK")],
    )

    result = DetectorAnnotationEvaluator.compare_annotation(annotation, timeline)

    assert result["structure_detected"] is True
    assert result["structure_detected_by_trigger"] is False
    assert result["first_structure_ms"] == trigger + 10_000
    assert result["first_structure_by_trigger_ms"] is None

    summary = DetectorAnnotationEvaluator._summarize([result])
    assert summary["structure_detected_valid"] == 1
    assert summary["structure_detected_by_trigger_valid"] == 0
    assert summary["per_detector"]["MICRO_PULLBACK"]["structure_recall"] == 1.0
    assert summary["per_detector"]["MICRO_PULLBACK"]["structure_recall_at_trigger"] == 0.0


def test_post_trigger_only_instance_is_matched_as_late_not_unmatched():
    trigger = 1_800_000_000_000
    annotation = {
        "annotation_id": "late-only",
        "session_id": "session",
        "symbol": "TEST",
        "setup_type": "micro_pullback",
        "trigger_ms": trigger,
        "valid_at_time": True,
        "outcome": "succeeded",
    }
    timeline = _timeline(
        "MICRO_PULLBACK",
        [(trigger + 20_000, "PULLBACK")],
    )

    result = DetectorAnnotationEvaluator.compare_annotation(annotation, timeline)

    assert result["matching"]["status"] == "matched"
    assert result["matching"]["basis"] == "nearest_post_trigger_instance"
    assert result["structure_detected"] is True
    assert result["structure_detected_by_trigger"] is False
