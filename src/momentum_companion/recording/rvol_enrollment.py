from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")
LOOKBACK_SESSIONS = 20


class EnrollmentRvolEvidenceCollector:
    """Optional research-only enrollment sidecar; never affects live decisions."""

    def __init__(
        self, rest_client: Any, root: Path, *, calendar_days: int = 50,
        minimum_interval_seconds: float = 0.5,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.rest = rest_client
        self.root = Path(root)
        self.calendar_days = calendar_days
        self.minimum_interval_seconds = minimum_interval_seconds
        self.now_provider = now_provider or (lambda: datetime.now(ET))
        self._lock = threading.Lock()
        self._last_request = 0.0

    def enroll(self, symbol: str, *, decision_date: date | None = None) -> dict[str, Any]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        cutoff = decision_date or self.now_provider().astimezone(ET).date()
        path = self.root / f"{normalized}.json"
        prior = self._read(path)
        if self._complete_prior_evidence(prior, cutoff):
            return prior
        with self._lock:
            delay = self.minimum_interval_seconds - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            end = datetime.combine(cutoff, clock_time(0, 0), tzinfo=ET)
            start = end - timedelta(days=self.calendar_days)
            response = self.rest.fetch_price_history(
                normalized, int(start.timestamp() * 1000), int(end.timestamp() * 1000), "1m"
            )
            self._last_request = time.monotonic()
        sessions = _eligible_sessions(
            response.get("candles") or [], cutoff=cutoff,
            start_ms=int(start.timestamp() * 1000), end_ms=int(end.timestamp() * 1000),
        )
        payload = {
            "schema_version": 1,
            "kind": "research_rvol_enrollment_evidence",
            "symbol": normalized,
            "source": "SCHWAB_PRICEHISTORY_1M_EXTENDED_HOURS",
            "request": {
                "start_et": start.isoformat(), "end_et_exclusive": end.isoformat(),
                "frequency": "one_minute", "extended_hours": True,
            },
            "receipt_timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "coverage": {
                "required_complete_sessions": LOOKBACK_SESSIONS,
                "complete_session_count": len(sessions),
                "complete": len(sessions) >= LOOKBACK_SESSIONS,
                "trading_dates": [item["trading_date"] for item in sessions],
                "current_decision_date_excluded": cutoff.isoformat(),
            },
            "sessions": sessions,
        }
        # A transient/truncated response must never replace usable evidence.
        if prior and (prior.get("coverage") or {}).get("complete") and not payload["coverage"]["complete"]:
            return prior
        _atomic_write(path, payload)
        return payload

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _complete_prior_evidence(payload: Mapping[str, Any] | None, cutoff: date) -> bool:
        if not payload or not (payload.get("coverage") or {}).get("complete"):
            return False
        if (payload.get("coverage") or {}).get("current_decision_date_excluded") != cutoff.isoformat():
            return False
        dates = [str(item.get("trading_date") or "") for item in payload.get("sessions") or []]
        return len(set(day for day in dates if day and day < cutoff.isoformat())) >= LOOKBACK_SESSIONS


def _eligible_sessions(candles: list[Mapping[str, Any]], *, cutoff: date, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in candles:
        try:
            stamp = int(raw["datetime"])
        except (KeyError, TypeError, ValueError):
            continue
        if stamp < start_ms or stamp >= end_ms:
            continue
        local = datetime.fromtimestamp(stamp / 1000, tz=ET)
        if local.date() >= cutoff or not clock_time(4, 0) <= local.time() < clock_time(20, 0):
            continue
        grouped.setdefault(local.date().isoformat(), []).append(dict(raw))
    sessions = []
    for day, rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda item: int(item["datetime"]))
        pre = [item for item in ordered if datetime.fromtimestamp(int(item["datetime"]) / 1000, tz=ET).time() < clock_time(9, 30)]
        rth = [item for item in ordered if clock_time(9, 30) <= datetime.fromtimestamp(int(item["datetime"]) / 1000, tz=ET).time() < clock_time(16, 0)]
        after = [item for item in ordered if datetime.fromtimestamp(int(item["datetime"]) / 1000, tz=ET).time() >= clock_time(16, 0)]
        if not pre or not rth:
            continue
        sessions.append({
            "trading_date": day,
            "first_candle_et": datetime.fromtimestamp(int(ordered[0]["datetime"]) / 1000, tz=ET).isoformat(),
            "last_candle_et": datetime.fromtimestamp(int(ordered[-1]["datetime"]) / 1000, tz=ET).isoformat(),
            "phase_cumulative": {
                "premarket": _cumulative(pre, clock_time(4, 0)),
                "regular": _cumulative(rth, clock_time(9, 30)),
                "after_hours": _cumulative(after, clock_time(16, 0)),
            },
            "candles": ordered,
        })
    return sessions


def _cumulative(rows: list[Mapping[str, Any]], phase_start: clock_time) -> list[dict[str, Any]]:
    total = 0.0
    points = []
    for row in rows:
        local = datetime.fromtimestamp(int(row["datetime"]) / 1000, tz=ET)
        total += max(0.0, float(row.get("volume") or 0))
        offset = int((datetime.combine(local.date(), local.time(), tzinfo=ET) - datetime.combine(local.date(), phase_start, tzinfo=ET)).total_seconds())
        points.append({"offset_seconds": offset, "cumulative_volume": total})
    return points


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
