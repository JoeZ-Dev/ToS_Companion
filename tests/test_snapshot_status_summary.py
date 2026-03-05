import pytest

try:
    from momentum_companion.ui.controller import snapshot_status_summary
except ImportError:
    pytest.skip("PySide6 unavailable", allow_module_level=True)


def test_snapshot_status_summary_flags():
    summary = snapshot_status_summary(
        "ABC",
        {"last": 10.5, "bid": 10.4, "ask": 10.6},
        [{"ts_ms": 1, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}],
        [{"ts_ms": 1, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}],
        None,
        None,
    )
    assert "has_quote=True" in summary
    assert "bars_1m=1" in summary
    assert "bars_5m=1" in summary


def test_snapshot_status_summary_missing_data():
    summary = snapshot_status_summary("XYZ", {}, [], [], None, None)
    assert "has_quote=False" in summary
    assert "has_1m=False" in summary
    assert "has_5m=False" in summary
