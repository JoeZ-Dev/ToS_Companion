from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol

from momentum_companion.setup_engine.pattern_contracts import PatternObservation


class PatternDetector(Protocol):
    name: str

    def detect(self, symbol: str, bars: Iterable) -> PatternObservation | None:
        ...


@dataclass
class PatternEngine:
    """Pure deterministic registry/orchestrator for pluggable pattern detectors."""

    detectors: list[PatternDetector] = field(default_factory=list)

    def register(self, detector: PatternDetector) -> None:
        if any(existing.name == detector.name for existing in self.detectors):
            raise ValueError(f"pattern detector already registered: {detector.name}")
        self.detectors.append(detector)

    def detect(self, symbol: str, bars: Iterable) -> list[PatternObservation]:
        materialized = list(bars)
        observations: list[PatternObservation] = []
        for detector in self.detectors:
            observation = detector.detect(symbol, materialized)
            if observation is not None:
                observations.append(observation)
        return observations

    def detect_dicts(self, symbol: str, bars: Iterable) -> list[dict]:
        return [observation.to_dict() for observation in self.detect(symbol, bars)]
