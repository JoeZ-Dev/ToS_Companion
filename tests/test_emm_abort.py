import json

from momentum_companion.execution.emm_engine import EMMEngine


class DummyRest:
    def place_order(self, *args, **kwargs):
        return "oid"

    def replace_order(self, *args, **kwargs):
        return "oid"

    def cancel_order(self, *args, **kwargs):
        return None


class FakeJournal:
    def __init__(self):
        self.events = []

    def append_event(self, event):
        self.events.append(event)


def test_emm_no_quote_abort():
    rest = DummyRest()
    emm = EMMEngine(rest)
    status = emm.execute("acc", "BUY", 1, 10.0, {}, {"ask": None})
    assert status == "emm_no_quote"


def test_emm_timeout_rounds_tick():
    rest = DummyRest()
    emm = EMMEngine(rest)
    status = emm.execute("acc", "BUY", 1, 10.0, {"emm_max_chase_duration_s": 0.001}, {"ask": 10.123})
    assert status == "emm_timeout"


def test_emm_stale_quote_journal():
    rest = DummyRest()
    journal = FakeJournal()
    emm = EMMEngine(rest, journal)
    status = emm.execute(
        "acc",
        "BUY",
        1,
        10.0,
        {"emm_max_chase_duration_s": 0.1},
        {"ask": 10.0, "ts_ms": int(0)},  # very old timestamp
        "AAPL",
    )
    assert status == "emm_stale_quote"
    assert journal.events[-1]["event_type"] == "STALE_QUOTE"
    notes = json.loads(journal.events[-1]["notes_json"])
    assert notes["last_quote_age_ms"] is not None


def test_emm_disconnect_journal():
    journal = FakeJournal()
    emm = EMMEngine(DummyRest(), journal)
    emm.abort_disconnect("AAPL", ["oid1"])
    assert journal.events[-1]["event_type"] == "DISCONNECT"
