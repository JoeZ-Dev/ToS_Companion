from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from momentum_companion.setup_engine.pattern_contracts import PatternObservation
from momentum_companion.setup_engine.patterns import detect_ascending_triangle, detect_micro_pullback


Detector = Callable[[str, Iterable], PatternObservation | None]


@dataclass
class PatternEngine:
    """Pure deterministic pattern orchestrator.

    The engine intentionally has no Schwab, UI, execution, or LLM dependencies so
    the same logic can run against live bars and recorded/replayed sessions.
    """

    detectors: list[Detector] = field(
        default_factory=lambda: [detect_ascending_triangle, detect_micro_pullback]
    )

    def detect(self, symbol: str, bars: Iterable) -> list[PatternObservation]:
        materialized = list(bars)
        observations: list[PatternObservation] = []
        for detector in self.detectors:
            observation = detector(symbol, materialized)
            if observation is not None:
                observations.append(observation)
        return observations

    def detect_dicts(self, symbol: str, bars: Iterable) -> list[dict]:
        return [observation.to_dict() for observation in self.detect(symbol, bars)]
