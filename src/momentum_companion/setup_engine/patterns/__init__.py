from momentum_companion.setup_engine.pattern_engine import PatternEngine
from momentum_companion.setup_engine.patterns.ascending_triangle import AscendingTriangleDetector
from momentum_companion.setup_engine.patterns.micro_pullback import MicroPullbackDetector


def build_default_pattern_engine() -> PatternEngine:
    engine = PatternEngine()
    engine.register(AscendingTriangleDetector())
    engine.register(MicroPullbackDetector())
    return engine


__all__ = [
    "AscendingTriangleDetector",
    "MicroPullbackDetector",
    "build_default_pattern_engine",
]
