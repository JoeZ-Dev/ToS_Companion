import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from momentum_companion.recording.backfill import (
    HistoricalBackfillManager,
    seconds_until_next_backfill,
)
from momentum_companion.recording.market_day import MarketDayRecorder
from momentum_companion.replay.engine import ReplayEngine

ET = ZoneInfo("America/New_York")


class FakeRest:
    def __init__(self, candles):
        self.candles = candles
        self.calls = []

    def fetch_price_history(self, symbol, start_ms, end_ms, freq):
        self.calls.append((symbol, start_ms, end_ms, freq))
        return {"candles": list(self.candles)}


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def test_backfill_scans_completed_prior_session_and_keeps_target_day(tmp_path: Path):
    target = datetime(2026, 9, 24, 9, 0, tzinfo=ET)
    previous = datetime(2026, 9, 23, 12, 0, tzinfo=ET)
    recorder = MarketDayRecorder(
        ["GCTK"],
        output_root=tmp_path,
        started_at=target,
    )
    recorder.record_payload(
        {
            "data": [
                {
                    "service": "LEVELONE_EQUITIES",
                    "timestamp": _ms(target),
                    "content": [{"key": "GCTK", "3": 4.20, "8": 1000}],
                }
            ]
        }
    )
    recorder.close(stop_reason="browser_stop")

    rest = FakeRest(
        [
            {"datetime": _ms(previous), "open": 9, "high": 9, "low": 9, "close": 9, "volume": 10},
            {
                "datetime": _ms(datetime(2026, 9, 24, 4, 1, tzinfo=ET)),
                "open": 4.0,
                "high": 4.1,
                "low": 3.9,
                "close": 4.05,
                "volume": 100,
            },
            {
                "datetime": _ms(datetime(2026, 9, 24, 7, 0, tzinfo=ET)),
                "open": 4.1,
                "high": 4.2,
                "low": 4.0,
                "close": 4.15,
                "volume": 200,
            },
        ]
    )
    now = datetime(2026, 9, 25, 7, 1, tzinfo=ET)
    manager = HistoricalBackfillManager(
        rest,
        recordings_root=tmp_path,
        now_provider=lambda: now,
    )

    summary = manager.run_pending()

    assert summary["symbols_completed"] == 1
    assert len(rest.calls) == 1
    symbol, start_ms, end_ms, freq = rest.calls[0]
    assert symbol == "GCTK"
    assert freq == "1m"
    assert datetime.fromtimestamp(start_ms / 1000, ET) == datetime(2026, 9, 17, 0, 0, tzinfo=ET)
    assert datetime.fromtimestamp(end_ms / 1000, ET).date().isoformat() == "2026-09-24"

    history = json.loads((recorder.session_dir / "GCTK_history.json").read_text())
    assert [c["datetime"] for c in history["candles"]] == [
        _ms(datetime(2026, 9, 24, 4, 1, tzinfo=ET)),
        _ms(datetime(2026, 9, 24, 7, 0, tzinfo=ET)),
    ]

    manifest = json.loads((recorder.session_dir / "manifest.json").read_text())
    state = manifest["historical_backfill"]
    assert state["status"] == "complete"
    assert state["symbols"]["GCTK"]["pre_7_candles"] == 1
    assert state["symbols"]["GCTK"]["first_bar_et"].startswith("2026-09-24T04:01:00")


def test_completed_backfill_is_idempotent(tmp_path: Path):
    started = datetime(2026, 9, 24, 8, 0, tzinfo=ET)
    recorder = MarketDayRecorder(["SPY"], output_root=tmp_path, started_at=started)
    recorder.close()

    rest = FakeRest(
        [{
            "datetime": _ms(datetime(2026, 9, 24, 4, 0, tzinfo=ET)),
            "open": 1,
            "high": 1,
            "low": 1,
            "close": 1,
            "volume": 1,
        }]
    )
    manager = HistoricalBackfillManager(
        rest,
        recordings_root=tmp_path,
        now_provider=lambda: datetime(2026, 9, 25, 8, 0, tzinfo=ET),
    )

    manager.run_pending()
    manager.run_pending()

    assert len(rest.calls) == 1


def test_backfill_failure_stays_pending_for_next_run(tmp_path: Path):
    started = datetime(2026, 9, 24, 8, 0, tzinfo=ET)
    recorder = MarketDayRecorder(["SPY"], output_root=tmp_path, started_at=started)
    recorder.close()

    rest = FakeRest([])
    manager = HistoricalBackfillManager(
        rest,
        recordings_root=tmp_path,
        now_provider=lambda: datetime(2026, 9, 25, 8, 0, tzinfo=ET),
    )

    summary = manager.run_pending()
    manifest = json.loads((recorder.session_dir / "manifest.json").read_text())

    assert summary["symbols_failed"] == 1
    assert manifest["historical_backfill"]["status"] == "pending"
    assert manifest["historical_backfill"]["symbols"]["SPY"]["status"] == "pending"


def test_next_backfill_trigger_is_7am_et():
    before = datetime(2026, 9, 25, 6, 30, tzinfo=ET)
    after = datetime(2026, 9, 25, 7, 30, tzinfo=ET)

    assert seconds_until_next_backfill(before) == 30 * 60
    assert seconds_until_next_backfill(after) == (23 * 60 + 30) * 60


def test_replay_seeds_vwap_from_backfilled_history_before_first_event(tmp_path: Path):
    session = tmp_path / "2026-09-24_080000_session"
    session.mkdir()
    first_event = datetime(2026, 9, 24, 8, 0, tzinfo=ET)
    manifest = {
        "schema_version": 1,
        "kind": "market_day_recording",
        "symbols": ["GCTK"],
        "services": ["LEVELONE_EQUITIES"],
        "started_at_et": first_event.isoformat(),
        "ended_at_et": datetime(2026, 9, 24, 15, 0, tzinfo=ET).isoformat(),
        "counts": {"GCTK": {"LEVELONE_EQUITIES": 1}},
    }
    (session / "manifest.json").write_text(json.dumps(manifest))
    event = {
        "schema_version": 1,
        "kind": "market_event",
        "service": "LEVELONE_EQUITIES",
        "symbol": "GCTK",
        "stream_ts_ms": _ms(first_event),
        "received_at": first_event.isoformat(),
        "raw": {"key": "GCTK", "1": 4.19, "2": 4.21, "3": 4.20, "8": 1000},
    }
    (session / "GCTK.jsonl").write_text(json.dumps(event) + "\n")
    history = {
        "schema_version": 1,
        "kind": "historical_backfill",
        "symbol": "GCTK",
        "date_et": "2026-09-24",
        "source": "SCHWAB_PRICEHISTORY_1M",
        "candles": [
            {
                "datetime": _ms(datetime(2026, 9, 24, 4, 0, tzinfo=ET)),
                "open": 4.0,
                "high": 4.2,
                "low": 3.9,
                "close": 4.1,
                "volume": 100,
            },
            {
                "datetime": _ms(datetime(2026, 9, 24, 7, 59, tzinfo=ET)),
                "open": 4.1,
                "high": 4.3,
                "low": 4.0,
                "close": 4.2,
                "volume": 200,
            },
        ],
    }
    (session / "GCTK_history.json").write_text(json.dumps(history))

    replay = ReplayEngine(recordings_root=tmp_path)
    replay.load(session.name, "GCTK")
    snapshot = replay.snapshot()

    symbol_state = snapshot["session"]["symbols"]["GCTK"]
    assert len(symbol_state["history_bars"]) == 2
    assert symbol_state["history_bars"][0]["time"] == int(
        datetime(2026, 9, 24, 4, 0, tzinfo=ET).timestamp()
    )
    assert len(symbol_state["vwap_points"]) == 2

    replay.seek(0)
    assert len(replay.snapshot()["session"]["symbols"]["GCTK"]["vwap_points"]) == 2
