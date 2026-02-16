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
