from momentum_companion.evaluation.corpus_registry import (
    DEVELOPMENT_SESSIONS,
    HOLDOUT_SESSIONS,
    EVALUATION_BASELINE_REVISION,
    MICRO_PULLBACK_FROZEN_DETECTOR_REVISION,
    classify_session,
    metadata_for,
)


def test_known_sessions_are_development():
    assert len(DEVELOPMENT_SESSIONS) == 6
    assert classify_session("2026-09-25_083639_session") == "development"
    assert classify_session("2026-09-22_095504_IMCC-LHSW") == "development"


def test_new_sessions_are_not_silently_promoted_to_holdout():
    assert HOLDOUT_SESSIONS == frozenset()
    assert classify_session("future-session") == "unclassified"


def test_micro_pullback_metadata_records_frozen_detector_revision():
    metadata = metadata_for(
        "2026-09-25_083639_session",
        "MICRO_PULLBACK",
    ).to_dict()

    assert metadata["corpus"] == "development"
    assert metadata["detector_revision"] == MICRO_PULLBACK_FROZEN_DETECTOR_REVISION
    assert metadata["evaluation_baseline_revision"] == EVALUATION_BASELINE_REVISION


def test_other_detector_does_not_claim_micro_pullback_revision():
    metadata = metadata_for(
        "2026-09-25_083639_session",
        "ASCENDING_TRIANGLE",
    ).to_dict()

    assert metadata["corpus"] == "development"
    assert metadata["detector_revision"] is None
