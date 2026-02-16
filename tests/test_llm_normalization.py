from momentum_companion.llm.normalization import normalize_snapshot


def test_normalize_snapshot_maps_fields():
    raw = {"status": "ok", "data_quality": "ok", "as_of_ts_ms": 1, "symbol": "AAPL", "market_state": "normal", "bars_window_5m": [1, 2]}
    quote = {"bid": 10, "ask": 11, "last": 10.5, "volume": 1000}
    payload = normalize_snapshot(raw, "SEAMLESS", quote)
    assert payload["schema_version"] == "AE-1.1"
    assert payload["session_mode"] == "SEAMLESS"
    assert payload["bars_window"] == [1, 2]
