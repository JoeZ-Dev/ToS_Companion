from momentum_companion.setup_engine.pattern_engine import PatternEngine
from momentum_companion.setup_engine.pattern_service import PatternEvaluationService
from momentum_companion.setup_engine.pattern_contracts import PatternObservation, PatternState


def bar(t, close):
    return {
        "time": t,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100,
    }


class RecordingDetector:
    name = "TEST_PATTERN"

    def __init__(self):
        self.seen_lengths = []

    def detect(self, symbol, bars):
        materialized = list(bars)
        self.seen_lengths.append(len(materialized))
        if len(materialized) < 3:
            return None
        return PatternObservation(
            symbol=symbol,
            pattern_type=self.name,
            state=PatternState.FORMING,
            started_at=materialized[0]["time"],
            updated_at=materialized[-1]["time"],
            evidence={"bars_seen": len(materialized)},
        )


def test_live_and_replay_can_share_same_completed_bar_boundary():
    detector = RecordingDetector()
    engine = PatternEngine()
    engine.register(detector)
    service = PatternEvaluationService(engine=engine, max_bars_per_symbol=10)

    assert service.ingest_completed_bar("abcd", bar(0, 10.0)) == []
    assert service.ingest_completed_bar("abcd", bar(10, 10.1)) == []
    observations = service.ingest_completed_bar("abcd", bar(20, 10.2))

    assert observations[0]["pattern_type"] == "TEST_PATTERN"
    assert observations[0]["symbol"] == "ABCD"
    assert observations[0]["evidence"]["bars_seen"] == 3
    assert detector.seen_lengths == [1, 2, 3]


def test_seed_bars_supports_replay_or_history_without_special_detector_path():
    detector = RecordingDetector()
    engine = PatternEngine()
    engine.register(detector)
    service = PatternEvaluationService(engine=engine, max_bars_per_symbol=10)

    observations = service.seed_bars(
        "xyz",
        [bar(0, 5.0), bar(10, 5.1), bar(20, 5.2), bar(30, 5.3)],
    )

    assert observations[0]["pattern_type"] == "TEST_PATTERN"
    assert observations[0]["evidence"]["bars_seen"] == 4
    assert len(service.bars("XYZ")) == 4


def test_evaluator_keeps_bounded_per_symbol_windows():
    detector = RecordingDetector()
    engine = PatternEngine()
    engine.register(detector)
    service = PatternEvaluationService(engine=engine, max_bars_per_symbol=3)

    for i in range(5):
        service.ingest_completed_bar("ABCD", bar(i * 10, 10 + i / 10))

    retained = service.bars("ABCD")
    assert len(retained) == 3
    assert retained[0]["time"] == 20
    assert retained[-1]["time"] == 40


def test_symbols_are_isolated_and_resettable():
    detector = RecordingDetector()
    engine = PatternEngine()
    engine.register(detector)
    service = PatternEvaluationService(engine=engine)

    service.seed_bars("AAA", [bar(0, 1), bar(10, 2), bar(20, 3)])
    service.seed_bars("BBB", [bar(0, 4), bar(10, 5), bar(20, 6)])

    assert service.observations("AAA")
    assert service.observations("BBB")

    service.reset("AAA")
    assert service.observations("AAA") == []
    assert service.bars("AAA") == []
    assert service.observations("BBB")

    service.reset()
    assert service.observations("BBB") == []



def test_halt_and_resume_context_is_attached_to_pattern_evidence():
    detector = RecordingDetector()
    engine = PatternEngine()
    engine.register(detector)
    service = PatternEvaluationService(engine=engine)

    service.update_security_status("AAA", "Halted", 1000)
    service.update_security_status("AAA", "Normal", 5000)
    service.ingest_completed_bar("AAA", bar(0, 1.0))
    service.ingest_completed_bar("AAA", bar(10, 1.1))
    observations = service.ingest_completed_bar("AAA", bar(20, 1.2))

    halt = observations[0]["evidence"]["halt_context"]
    assert observations[0]["evidence"]["trading_status"] == "NORMAL"
    assert halt["last_halt_start_ms"] == 1000
    assert halt["last_resume_ms"] == 5000
    assert halt["halted_since_ms"] is None
