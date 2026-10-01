# Evaluation Corpus Discipline

## Purpose

This registry prevents detector development from silently overfitting to recordings that have already been inspected during detector design.

The current six recorded sessions are the **development corpus**. They may be used to debug evaluator correctness and understand detector behavior, but they are no longer valid as unseen evidence for tuning the frozen micro-pullback detector.

## Development corpus

- `2026-09-25_083639_session`
- `2026-09-24_080815_session`
- `2026-09-23_090050_session`
- `2026-09-23_084905_session`
- `2026-09-23_073759_session`
- `2026-09-22_095504_IMCC-LHSW`

These sessions remain useful for regression tests and diagnostics.

## Holdout corpus

No holdout sessions are registered yet.

A future recording becomes holdout only when it is explicitly reserved through
the persisted corpus-classification API before detector-specific failure
inspection or detector changes based on that recording.

New sessions are therefore classified as `unclassified` by default. They are never silently treated as holdout.

## Frozen micro-pullback detector

The micro-pullback detector is frozen at detector revision:

`33181b1ecf1bcce446a25ca136688342262262ea`

That revision is the last detector-semantic change in the current development cycle.

The evaluation baseline after evaluator-only corrections is:

`4d6a3a6ea6811cfa3a128e6618450f212497136e`

Evaluator-only fixes may continue when they correct measurement or reporting defects. Detector semantics, thresholds, and pattern logic should not be changed using the existing development corpus.

## Holdout procedure

1. Record new sessions normally.
2. Before inspecting detector-specific misses or tuning behavior, explicitly
   reserve selected sessions with
   `PUT /api/corpus/classifications/{session_id}` and classification `holdout`.
3. Run the frozen detector against the holdout.
4. Produce verification annotations independently using the existing blind review workflow.
5. Compare aggregate detector results against the holdout labels.
6. Do not modify the detector in response to one or two individual holdout failures.
7. If the holdout reveals a reason to reopen development, formally end that holdout cycle. Any inspected holdout sessions then become development data and a new unseen holdout must be collected.

The persisted registry is stored outside raw recording directories. Changing a
holdout to another classification requires the explicit
`confirm_holdout_relabel` action and appends an audit-history entry. The fixed
six-session development baseline cannot be reclassified through this workflow.

## Audit provenance

Detector-audit output includes corpus metadata on every result and a top-level corpus registry summary. For micro-pullback annotations, the output also records the frozen detector revision so later reports can be traced back to the exact detector implementation used for the development freeze.
