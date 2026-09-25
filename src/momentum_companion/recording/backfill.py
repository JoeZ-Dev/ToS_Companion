from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
BACKFILL_HOUR_ET = 7
BACKFILL_SCHEMA_VERSION = 1


def seconds_until_next_backfill(now: datetime | None = None) -> float:
    current = now or datetime.now(ET)
    current = current.replace(tzinfo=ET) if current.tzinfo is None else current.astimezone(ET)
    target = datetime.combine(current.date(), dtime(hour=BACKFILL_HOUR_ET), tzinfo=ET)
    if current >= target:
        target += timedelta(days=1)
    return max(0.0, (target - current).total_seconds())


class HistoricalBackfillManager:
    """Enrich completed recordings with prior-day Schwab 1m history.

    Schwab exposes richer pre-7 AM history for completed days when the target
    date is requested as a non-leading day in a multi-day window. Raw capture
    files are never rewritten; one history file per symbol is written beside
    them and the manifest records enrichment status.
    """

    def __init__(
        self,
        rest_client: Any,
        *,
        recordings_root: Path | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.rest = rest_client
        self.root = recordings_root or (Path.home() / ".tos_companion" / "recordings")
        self._now_provider = now_provider or (lambda: datetime.now(ET))
        self._lock = threading.Lock()

    def run_pending(self) -> dict[str, int]:
        summary = {"sessions_scanned": 0, "sessions_completed": 0, "symbols_completed": 0, "symbols_failed": 0}
        if not self.root.exists():
            return summary

        with self._lock:
            today = self._now_et().date()
            for manifest_path in sorted(self.root.glob("*/manifest.json")):
                manifest = self._read_manifest(manifest_path)
                if not manifest or manifest.get("kind") != "market_day_recording":
                    continue
                summary["sessions_scanned"] += 1
                target_date = self._recording_date(manifest)
                if target_date is None or target_date >= today or not manifest.get("ended_at_et"):
                    continue

                state = manifest.setdefault("historical_backfill", {})
                symbols_state = state.setdefault("symbols", {})
                all_complete = True

                for raw_symbol in manifest.get("symbols") or []:
                    symbol = str(raw_symbol).strip().upper()
                    if not symbol:
                        continue
                    prior = symbols_state.get(symbol) or {}
                    if prior.get("status") == "complete":
                        continue
                    try:
                        candles = self._fetch_target_day(symbol, target_date)
                        path = manifest_path.parent / f"{symbol}_history.json"
                        payload = {
                            "schema_version": BACKFILL_SCHEMA_VERSION,
                            "kind": "historical_backfill",
                            "symbol": symbol,
                            "date_et": target_date.isoformat(),
                            "source": "SCHWAB_PRICEHISTORY_1M",
                            "candles": candles,
                        }
                        self._atomic_write_json(path, payload)
                        before7 = sum(
                            1
                            for candle in candles
                            if self._candle_et(candle).hour < 7
                        )
                        symbols_state[symbol] = {
                            "status": "complete",
                            "completed_at_et": self._now_et().isoformat(),
                            "candles": len(candles),
                            "pre_7_candles": before7,
                            "first_bar_et": self._candle_et(candles[0]).isoformat() if candles else None,
                            "last_bar_et": self._candle_et(candles[-1]).isoformat() if candles else None,
                            "file": path.name,
                        }
                        summary["symbols_completed"] += 1
                    except Exception as exc:
                        all_complete = False
                        symbols_state[symbol] = {
                            "status": "pending",
                            "last_attempt_at_et": self._now_et().isoformat(),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                        summary["symbols_failed"] += 1

                statuses = [
                    (symbols_state.get(str(s).strip().upper()) or {}).get("status")
                    for s in manifest.get("symbols") or []
                    if str(s).strip()
                ]
                if statuses and all(status == "complete" for status in statuses):
                    state["status"] = "complete"
                    state["completed_at_et"] = self._now_et().isoformat()
                    summary["sessions_completed"] += 1
                else:
                    state["status"] = "pending"
                self._atomic_write_json(manifest_path, manifest)

        return summary

    def _fetch_target_day(self, symbol: str, target_date) -> list[dict]:
        # Use a wide enough window that the target is not the first trading
        # day returned, including Mondays and holiday-adjacent sessions.
        previous = target_date - timedelta(days=7)
        start = datetime(previous.year, previous.month, previous.day, tzinfo=ET)
        end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=ET)
        response = self.rest.fetch_price_history(
            symbol,
            int(start.timestamp() * 1000),
            int(end.timestamp() * 1000),
            "1m",
        )
        candles = [
            dict(candle)
            for candle in (response.get("candles") or [])
            if candle.get("datetime") is not None
            and self._candle_et(candle).date() == target_date
        ]
        candles.sort(key=lambda candle: int(candle["datetime"]))
        if not candles:
            raise RuntimeError("no target-day candles returned")
        return candles

    def _recording_date(self, manifest: dict):
        started = manifest.get("started_at_et")
        if not started:
            return None
        try:
            value = datetime.fromisoformat(str(started))
            if value.tzinfo is None:
                value = value.replace(tzinfo=ET)
            return value.astimezone(ET).date()
        except ValueError:
            return None

    def _candle_et(self, candle: dict) -> datetime:
        return datetime.fromtimestamp(int(candle["datetime"]) / 1000, tz=ET)

    def _now_et(self) -> datetime:
        value = self._now_provider()
        return value.replace(tzinfo=ET) if value.tzinfo is None else value.astimezone(ET)

    @staticmethod
    def _read_manifest(path: Path) -> dict | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)


def load_backfill_candles(
    session_dir: Path,
    symbol: str,
    *,
    through_ms: int | None = None,
) -> list[dict]:
    normalized = str(symbol or "").strip().upper()
    path = Path(session_dir) / f"{normalized}_history.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    if payload.get("kind") != "historical_backfill":
        return []
    candles = []
    for candle in payload.get("candles") or []:
        ts = candle.get("datetime")
        if ts is None:
            continue
        if through_ms is not None and int(ts) > int(through_ms):
            continue
        candles.append(dict(candle))
    candles.sort(key=lambda candle: int(candle["datetime"]))
    return candles
