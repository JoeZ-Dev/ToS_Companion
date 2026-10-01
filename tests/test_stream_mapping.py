from momentum_companion.clients.stream_mapping import LevelOneCache


def test_stream_mapping_emits_when_required_fields_present():
    cache = LevelOneCache()
    msg1 = {
        "service": "LEVELONE_EQUITIES",
        "timestamp": 1710000000000,
        "content": [{"key": "AAPL", "1": 100.0, "2": 101.0, "3": 100.5, "8": 1000}],
    }
    event = cache.process_message(msg1)
    assert event is not None
    assert event["symbol"] == "AAPL"
    assert event["bid"] == 100.0
    assert event["volume"] == 1000


def test_stream_mapping_drops_until_required_fields_available():
    cache = LevelOneCache()
    partial = {
        "service": "LEVELONE_EQUITIES",
        "timestamp": 1710000000000,
        "content": [{"key": "AAPL", "1": 100.0}],
    }
    assert cache.process_message(partial) is None
    follow = {
        "service": "LEVELONE_EQUITIES",
        "timestamp": 1710000005000,
        "content": [{"key": "AAPL", "2": 101.0, "3": 100.5, "8": 1000}],
    }
    event = cache.process_message(follow)
    assert event is not None
    assert event["ask"] == 101.0
    assert event["last"] == 100.5


def test_stream_mapping_raises_on_wrong_service():
    cache = LevelOneCache()
    msg = {"service": "QUOTE", "timestamp": 0, "content": [{"key": "AAPL"}]}
    try:
        cache.process_message(msg)
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_stream_mapping_preserves_halt_htb_and_relative_strength_context():
    cache = LevelOneCache()
    payload = {
        "service": "LEVELONE_EQUITIES",
        "timestamp": 1710000000000,
        "content": [{
            "key": "AIFF",
            "1": 4.10,
            "2": 4.12,
            "3": 4.11,
            "8": 123456,
            "32": "Halted",
            "42": 85.5,
            "43": 12.25,
            "46": 5000,
            "47": 37.5,
            "48": 1,
            "49": 1,
        }],
    }

    event = cache.process_message(payload)

    assert event is not None
    assert event["security_status"] == "Halted"
    assert event["net_percentage_change"] == 85.5
    assert event["regular_market_percentage_change"] == 12.25
    assert event["hard_to_borrow_quantity"] == 5000
    assert event["hard_to_borrow_rate"] == 37.5
    assert event["hard_to_borrow"] is True
    assert event["shortable"] is True
