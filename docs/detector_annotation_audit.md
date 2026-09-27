# Detector vs Annotation Audit

## Purpose

The detector audit compares the current replay pattern detectors against the stored **verification** annotations produced by the recording-review workflow.

It is descriptive research infrastructure. It does not change detector thresholds, strategy configuration, annotations, recordings, or live behavior.

## Endpoint

### POST /api/evaluation/detector-audit

Request:

    {
      "session_id": null,
      "symbol": null,
      "default_lookback_ms": 300000,
      "post_trigger_ms": 120000
    }

`session_id` and `symbol` are optional filters. With both omitted, the endpoint audits all stored verification annotations.

The evaluator replays each unique session/symbol once through the current `ReplayEngine`, retains the pattern observation timeline, and compares annotations to detector observations near each annotated trigger.

## Current detector mapping

Only setup types represented by the current detector registry are scored.

Current aliases:

- `ascending_triangle` -> `ASCENDING_TRIANGLE`
- `micro_pullback` -> `MICRO_PULLBACK`
- `micro_pullback_breakout` -> `MICRO_PULLBACK`

Other verified setup types are returned as `supported_by_current_detector_registry: false`. They are not counted as detector misses.

## Instance matching

The evaluator matches each annotation to one detector instance before scoring it.

Why this matters: the same detector can emit multiple formations for the same symbol inside a broad lookback window. Without instance matching, an older completed micro pullback can be incorrectly credited to a later annotated setup.

Matching rules:

- if the annotation has `setup_start_ms`, use that timestamp as an eligibility window rather than as the final selector
- among setup-window-eligible instances that reach the detector trigger state, prefer the instance whose trigger-state observation is closest to the annotated trigger
- if no eligible instance reaches a trigger state, prefer the eligible structure observation closest to the annotated trigger
- otherwise, when no `setup_start_ms` exists, prefer the most recently formed detector instance that already existed by the annotated trigger
- once an instance is selected, only observations with that `pattern_id` are used for structure, trigger, state, and latency scoring
- if no plausible instance matches, return `matching.status = "no_matching_instance"` instead of borrowing an older pattern

Current setup-start tolerances are intentionally narrow:
- `MICRO_PULLBACK`: 2 minutes
- `ASCENDING_TRIANGLE`: 5 minutes

These are evaluator association tolerances, not detector thresholds or trading rules. The matched result also reports `matched_trigger_distance_ms` and `nearest_observation_distance_ms` so instance selection is inspectable.

## Structure vs trigger-state detection

The audit deliberately separates two questions.

### Structure detected

A detector emitted any observation for the mapped pattern within the local comparison window.

This measures whether the detector recognized the underlying structure.

### Trigger detected

A detector emitted a trigger-state observation:

- `ASCENDING_TRIANGLE`: `BREAKOUT`
- `MICRO_PULLBACK`: `CONTINUATION`

This measures whether the detector progressed to the state corresponding most closely to the annotated trigger.

A micro-pullback detector sitting in `PULLBACK` or `TURNING` is therefore a structure detection, but not a continuation trigger.

## Timing

For each supported annotation the result includes:

- `first_structure_ms`
- `first_trigger_state_ms`
- `trigger_latency_ms`
- `state_at_annotated_trigger`
- `fired_by_annotated_trigger`
- all nearby detector observations and their evidence

`trigger_latency_ms` is:

    first detector trigger-state timestamp - annotated trigger timestamp

Negative values mean the detector triggered earlier than the annotation.
Positive values mean it triggered later.

The audit reports timing. It does not automatically claim that every early trigger is wrong.

## Rejected annotation false positives

For an annotation with `valid_at_time = false`, the audit marks:

    false_positive_on_rejected_candidate = true

only when the detector reached its trigger state on or before the rejected annotated trigger.

A forming/pullback observation alone is not counted as a trigger false positive.

This is especially important for the current micro-pullback corpus, where several discovery candidates were rejected because the proposed trigger occurred during the pullback before continuation.

## Trigger-time structure recall

The audit reports both broad-window structure detection and trigger-time structure detection.

- `structure_detected` means the matched detector instance appeared anywhere in the comparison window, including after the annotation trigger.
- `structure_detected_by_trigger` means the matched detector instance had already appeared by the annotated trigger timestamp.

Aggregate output therefore includes `structure_recall_at_trigger` separately from broad-window `structure_recall`. Post-trigger detections remain useful for latency analysis but are not credited as trigger-time recall.

## Aggregate report

The response summary includes:

- verification annotations
- supported and unsupported annotations
- valid/rejected supported labels
- structure detections on verified-valid labels
- trigger detections on verified-valid labels
- missed valid structures
- false positives on rejected labels
- median trigger latency
- early/on-time/late trigger counts
- per-detector structure recall
- per-detector trigger recall
- false-positive rate on rejected labels
- unsupported setup types

These metrics describe agreement with the labeled corpus. They are not performance estimates, profitability claims, or threshold-tuning instructions.

## Intended workflow

1. Freeze the current detector implementation.
2. Run the audit over all verification annotations.
3. Inspect misses, premature trigger states, and latency outliers.
4. For micro pullbacks, first determine whether the detector is confusing pullback formation with continuation.
5. Only after understanding current-detector behavior should detector semantics be changed.
6. Re-run the identical audit after any detector change.
7. Add new detector types only after their label definitions are sufficiently consistent.

The same corpus should remain stable across comparisons so changes can be evaluated against identical evidence.
