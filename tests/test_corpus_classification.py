import json

import pytest

from momentum_companion.evaluation.corpus_classification import (
    CorpusClassificationStore,
)
from momentum_companion.evaluation.detector_audit import DetectorAnnotationEvaluator


def test_unknown_session_defaults_to_unclassified_without_persisting(tmp_path):
    store = CorpusClassificationStore(tmp_path / "registry.json")

    item = store.get("future-session")

    assert item["classification"] == "unclassified"
    assert item["classified_at_utc"] is None
    assert item["source"] == "default"
    assert not store.path.exists()


def test_classification_is_persisted_with_timestamp_note_and_history(tmp_path):
    path = tmp_path / "registry.json"
    store = CorpusClassificationStore(path)

    item = store.classify("future-session", "holdout", note="Reserved before review")

    assert item["classification"] == "holdout"
    assert item["classified_at_utc"].endswith("Z")
    assert item["note"] == "Reserved before review"
    assert item["history"][0]["from"] == "unclassified"
    assert CorpusClassificationStore(path).get("future-session")["classification"] == "holdout"
    assert json.loads(path.read_text())["schema_version"] == 1


def test_holdout_relabel_requires_explicit_confirmation_and_is_audited(tmp_path):
    store = CorpusClassificationStore(tmp_path / "registry.json")
    store.classify("future-session", "holdout")

    with pytest.raises(ValueError, match="confirm_holdout_relabel"):
        store.classify("future-session", "development")

    item = store.classify(
        "future-session",
        "development",
        note="Holdout cycle formally ended",
        confirm_holdout_relabel=True,
    )
    assert item["classification"] == "development"
    assert item["history"][-1]["holdout_relabel_confirmed"] is True


def test_fixed_development_baseline_cannot_be_reclassified(tmp_path):
    store = CorpusClassificationStore(tmp_path / "registry.json")
    session_id = "2026-09-25_083639_session"

    assert store.get(session_id)["classification"] == "development"
    assert store.get(session_id)["source"] == "repository_baseline"
    with pytest.raises(ValueError, match="fixed development"):
        store.classify(session_id, "holdout")


def test_corrupt_registry_fails_closed(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text("{not-json")
    store = CorpusClassificationStore(path)

    with pytest.raises(RuntimeError, match="invalid corpus classification registry"):
        store.get("future-session")


def test_metadata_uses_persisted_classification_and_frozen_revision(tmp_path):
    store = CorpusClassificationStore(tmp_path / "registry.json")
    store.classify("future-session", "holdout")

    metadata = store.metadata_for("future-session", "MICRO_PULLBACK")

    assert metadata["corpus"] == "holdout"
    assert metadata["classification_source"] == "persisted"
    assert metadata["classified_at_utc"] is not None
    assert metadata["detector_revision"] == "33181b1ecf1bcce446a25ca136688342262262ea"


def test_detector_comparison_uses_persisted_classification(tmp_path):
    store = CorpusClassificationStore(tmp_path / "registry.json")
    store.classify("future-session", "holdout")
    annotation = {
        "annotation_id": "a1",
        "session_id": "future-session",
        "symbol": "AEHL",
        "setup_type": "micro_pullback",
        "trigger_ms": 100_000,
        "valid_at_time": True,
    }

    result = DetectorAnnotationEvaluator.compare_annotation(
        annotation,
        [],
        corpus_store=store,
    )

    assert result["corpus"]["corpus"] == "holdout"
    assert result["corpus"]["classification_source"] == "persisted"


def test_detector_audit_registry_summary_includes_persisted_holdout(tmp_path):
    class EmptyAnnotations:
        def list(self, **kwargs):
            return []

    store = CorpusClassificationStore(tmp_path / "registry.json")
    store.classify("future-session", "holdout")
    evaluator = DetectorAnnotationEvaluator(
        recordings_root=tmp_path,
        annotation_store=EmptyAnnotations(),
        corpus_store=store,
    )

    report = evaluator.audit()

    assert "future-session" in report["corpus_registry"]["holdout_sessions"]
