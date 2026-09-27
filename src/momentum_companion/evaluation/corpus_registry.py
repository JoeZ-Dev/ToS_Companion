from __future__ import annotations

from dataclasses import dataclass


DEVELOPMENT_SESSIONS: frozenset[str] = frozenset(
    {
        "2026-09-25_083639_session",
        "2026-09-24_080815_session",
        "2026-09-23_090050_session",
        "2026-09-23_084905_session",
        "2026-09-23_073759_session",
        "2026-09-22_095504_IMCC-LHSW",
    }
)

# Holdout membership must be explicit. New recordings are intentionally left
# unclassified until they are reserved before detector-specific inspection.
HOLDOUT_SESSIONS: frozenset[str] = frozenset()

MICRO_PULLBACK_FROZEN_DETECTOR_REVISION = (
    "33181b1ecf1bcce446a25ca136688342262262ea"
)
EVALUATION_BASELINE_REVISION = "4d6a3a6ea6811cfa3a128e6618450f212497136e"


@dataclass(frozen=True)
class CorpusMetadata:
    corpus: str
    detector_revision: str | None
    evaluation_baseline_revision: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "corpus": self.corpus,
            "detector_revision": self.detector_revision,
            "evaluation_baseline_revision": self.evaluation_baseline_revision,
        }


def classify_session(session_id: str) -> str:
    if session_id in DEVELOPMENT_SESSIONS:
        return "development"
    if session_id in HOLDOUT_SESSIONS:
        return "holdout"
    return "unclassified"


def metadata_for(session_id: str, detector_type: str | None) -> CorpusMetadata:
    detector_revision = (
        MICRO_PULLBACK_FROZEN_DETECTOR_REVISION
        if detector_type == "MICRO_PULLBACK"
        else None
    )
    return CorpusMetadata(
        corpus=classify_session(session_id),
        detector_revision=detector_revision,
        evaluation_baseline_revision=EVALUATION_BASELINE_REVISION,
    )
