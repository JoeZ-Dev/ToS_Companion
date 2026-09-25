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



def test_stream_mapping_carries_halt_and_borrow_context():
    cache = LevelOneCache()
    event = cache.process_message({
        "service": "LEVELONE_EQUITIES",
        "timestamp": 1710000000000,
        "content": [{
            "key": "HALT",
            "1": 5.00,
            "2": 5.05,
            "3": 5.02,
            "8": 100000,
            "9": 200,
            "12": 4.00,
            "32": "Halted",
            "46": 2500,
            "47": 18.75,
            "48": 1,
            "49": 0,
        }],
    })

    assert event is not None
    assert event["last_size"] == 200
    assert event["previous_close"] == 4.00
    assert event["security_status"] == "Halted"
    assert event["hard_to_borrow"] is True
    assert event["shortable"] is False
    assert event["htb_quantity"] == 2500
    assert event["htb_rate"] == 18.75
