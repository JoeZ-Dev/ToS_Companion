from momentum_companion.setup_engine.pattern_engine import PatternEngine
from momentum_companion.setup_engine.patterns.ascending_triangle import AscendingTriangleDetector
from momentum_companion.setup_engine.patterns.micro_pullback import MicroPullbackDetector
from momentum_companion.setup_engine.patterns.local_resistance_breakout import (
    LocalResistanceBreakoutDetector,
)
from momentum_companion.setup_engine.patterns.tight_consolidation_breakout import (
    TightConsolidationBreakoutDetector,
)


def build_default_pattern_engine() -> PatternEngine:
    engine = PatternEngine()
    engine.register(AscendingTriangleDetector())
    engine.register(MicroPullbackDetector())
    engine.register(LocalResistanceBreakoutDetector())
    engine.register(TightConsolidationBreakoutDetector())
    return engine


__all__ = [
    "AscendingTriangleDetector",
    "MicroPullbackDetector",
    "LocalResistanceBreakoutDetector",
    "TightConsolidationBreakoutDetector",
    "build_default_pattern_engine",
]
