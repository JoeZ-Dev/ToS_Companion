from datetime import datetime
from pathlib import Path

from momentum_companion.recording.market_day import (
    ET,
    MarketDayRecorder,
    build_subscription_requests,
    normalize_symbols,
    reached_cutoff,
)


def test_normalize_symbols_supports_multiple_and_deduplicates():
    assert normalize_symbols([" aehL ", "TOPS", "aehl", ""]) == ["AEHL", "TOPS"]


def test_cutoff_is_3pm_eastern():
    assert reached_cutoff(datetime(2026, 9, 21, 14, 59, 59, tzinfo=ET)) is False
    assert reached_cutoff(datetime(2026, 9, 21, 15, 0, 0, tzinfo=ET)) is True


def test_subscription_requests_default_to_supported_level_one_only():
    info = {"schwabClientCustomerId": "c", "schwabClientCorrelId": "r"}
    requests = build_subscription_requests(info, ["AEHL", "TOPS"])
    assert [request["service"] for request in requests] == ["LEVELONE_EQUITIES"]
    assert requests[0]["parameters"]["keys"] == "AEHL,TOPS"


def test_timesales_requires_explicit_experimental_opt_in():
    info = {"schwabClientCustomerId": "c", "schwabClientCorrelId": "r"}
    requests = build_subscription_requests(
        info, ["AEHL", "TOPS"], include_timesales=True
    )
    assert [request["service"] for request in requests] == [
        "LEVELONE_EQUITIES",
        "TIMESALE_EQUITY",
    ]


def test_recorder_routes_each_stream_entry_to_its_symbol_file(tmp_path: Path):
    recorder = MarketDayRecorder(
        ["AEHL", "TOPS"],
        output_root=tmp_path,
        services={"LEVELONE_EQUITIES", "TIMESALE_EQUITY"},
    )
    payload = {
        "data": [
            {
                "service": "TIMESALE_EQUITY",
                "timestamp": 1234567890000,
                "content": [
                    {"key": "AEHL", "1": 1234567889000, "2": 3.21, "3": 100, "4": 77},
                    {"key": "TOPS", "1": 1234567889001, "2": 1.11, "3": 250, "4": 88},
                ],
            }
        ]
    }

    recorder.record_payload(payload, received_at="2026-09-21T13:00:00Z")
    recorder.close()

    aehl = (recorder.session_dir / "AEHL.jsonl").read_text()
    tops = (recorder.session_dir / "TOPS.jsonl").read_text()

    assert '"service":"TIMESALE_EQUITY"' in aehl
    assert '"symbol":"AEHL"' in aehl
    assert '"symbol":"TOPS"' not in aehl
    assert '"symbol":"TOPS"' in tops


def test_non_recorded_services_are_ignored(tmp_path: Path):
    recorder = MarketDayRecorder(["AEHL"], output_root=tmp_path)
    recorder.record_payload(
        {"data": [{"service": "CHART_EQUITY", "content": [{"key": "AEHL", "2": 3.2}]}]},
        received_at="2026-09-21T13:00:00Z",
    )
    recorder.close()

    assert not (recorder.session_dir / "AEHL.jsonl").exists()


def test_default_manifest_declares_level_one_only(tmp_path: Path):
    recorder = MarketDayRecorder(["AEHL"], output_root=tmp_path)
    recorder.close()

    import json
    manifest = json.loads((recorder.session_dir / "manifest.json").read_text())
    assert manifest["services"] == ["LEVELONE_EQUITIES"]
    assert "TIMESALE_EQUITY" not in manifest["counts"]["AEHL"]
