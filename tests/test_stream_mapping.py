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


def test_stream_mapping_preserves_halt_and_borrow_context():
    cache = LevelOneCache()
    message = {
        "service": "LEVELONE_EQUITIES",
        "timestamp": 1710000000000,
        "content": [{
            "key": "HALT",
            "1": 4.10,
            "2": 4.20,
            "3": 4.15,
            "8": 500000,
            "9": 250,
            "32": "Halted",
            "34": 1710000000000,
            "35": 1709999999000,
            "46": 12000,
            "47": 8.75,
            "48": 1,
            "49": 0,
        }],
    }

    event = cache.process_message(message)

    assert event is not None
    assert event["security_status"] == "Halted"
    assert event["hard_to_borrow"] is True
    assert event["hard_to_borrow_quantity"] == 12000
    assert event["hard_to_borrow_rate"] == 8.75
    assert event["shortable"] is False
    assert event["last_size"] == 250
    assert event["quote_time_ms"] == 1710000000000
    assert event["trade_time_ms"] == 1709999999000


def test_stream_mapping_treats_negative_borrow_flags_as_unknown():
    cache = LevelOneCache()
    event = cache.process_message({
        "service": "LEVELONE_EQUITIES",
        "timestamp": 1710000000000,
        "content": [{
            "key": "UNK",
            "1": 1.0,
            "2": 1.1,
            "3": 1.05,
            "48": -1,
            "49": -1,
        }],
    })

    assert event is not None
    assert event["hard_to_borrow"] is None
    assert event["shortable"] is None
