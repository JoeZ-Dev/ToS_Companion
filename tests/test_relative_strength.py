from momentum_companion.analysis.relative_strength import RelativeStrengthTracker


def test_relative_strength_ranks_watchlist_by_five_minute_return():
    tracker = RelativeStrengthTracker()
    start = 1_700_000_000_000

    tracker.ingest("AAA", start, 10.0)
    tracker.ingest("BBB", start, 10.0)
    tracker.ingest("AAA", start + 300_000, 12.0)
    tracker.ingest("BBB", start + 300_000, 11.0)

    snapshot = tracker.snapshot(["AAA", "BBB"])

    assert snapshot["AAA"]["return_5m_pct"] == 20.0
    assert snapshot["BBB"]["return_5m_pct"] == 10.0
    assert snapshot["AAA"]["rank_5m"] == 1
    assert snapshot["AAA"]["leader_5m"] is True
    assert snapshot["BBB"]["rank_5m"] == 2


def test_relative_strength_does_not_invent_history_before_watch():
    tracker = RelativeStrengthTracker()
    tracker.ingest("AAA", 1_700_000_000_000, 10.0)

    snapshot = tracker.snapshot(["AAA"])

    assert snapshot["AAA"]["return_1m_pct"] is None
    assert snapshot["AAA"]["return_5m_pct"] is None
    assert snapshot["AAA"]["rank_5m"] is None
