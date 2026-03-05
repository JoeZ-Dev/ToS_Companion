from momentum_companion.llm.normalization import normalize_snapshot


def test_normalize_passes_extra_fields():
    raw = {
        "status": "ok",
        "data_quality": "ok",
        "as_of_ts_ms": 1,
        "symbol": "ABC",
        "bars_window_5m": [],
        "derived": {"a": 1},
        "structure_context": {"x": 2},
        "volume_structure": {"y": 3},
    }
    quote = {"bid": 1, "ask": 2, "last": 1.5, "volume": 100}
    out = normalize_snapshot(raw, "RTH", quote)
    assert out.get("derived") == {"a": 1}
    assert out.get("structure_context") == {"x": 2}
    assert out.get("volume_structure") == {"y": 3}
