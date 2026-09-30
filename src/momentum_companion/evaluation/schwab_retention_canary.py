from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from momentum_companion.clients.schwab_rest import SchwabRestClient
from momentum_companion.clients.token_provider import TokenProvider


ET = ZoneInfo("America/New_York")
MINIMUM_COMPLETE_SESSIONS = 20


def analyze_response(
    *, symbol: str, response: Mapping[str, Any], requested_start_ms: int,
    requested_end_ms: int, receipt_timestamp: str,
) -> dict[str, Any]:
    """Describe minute-history retention without inferring missing zero-volume bars."""
    grouped: dict[str, list[int]] = {}
    out_of_bounds = 0
    for candle in response.get("candles") or []:
        try:
            stamp = int(candle["datetime"])
        except (KeyError, TypeError, ValueError):
            continue
        if stamp < requested_start_ms or stamp >= requested_end_ms:
            out_of_bounds += 1
            continue
        local = datetime.fromtimestamp(stamp / 1000, tz=ET)
        if clock_time(4, 0) <= local.time() < clock_time(20, 0):
            grouped.setdefault(local.date().isoformat(), []).append(stamp)

    dates = []
    complete = []
    partial = []
    for day, stamps in sorted(grouped.items()):
        ordered = sorted(set(stamps))
        locals_ = [datetime.fromtimestamp(value / 1000, tz=ET) for value in ordered]
        phase_counts = {
            "premarket": sum(item.time() < clock_time(9, 30) for item in locals_),
            "rth": sum(clock_time(9, 30) <= item.time() < clock_time(16, 0) for item in locals_),
            "after_hours": sum(item.time() >= clock_time(16, 0) for item in locals_),
        }
        gaps = []
        for left, right in zip(ordered, ordered[1:]):
            missing = (right - left) // 60_000 - 1
            if missing > 0:
                gaps.append({
                    "after": _iso(left), "before": _iso(right),
                    "missing_one_minute_intervals": int(missing),
                })
        # RVOL needs premarket and RTH phase accumulations. Schwab omits many
        # zero-volume minutes, so gaps are reported but do not by themselves
        # prove truncation. A date without evidence in either required phase is
        # partial and cannot enter the baseline.
        is_complete = phase_counts["premarket"] > 0 and phase_counts["rth"] > 0
        record = {
            "trading_date": day,
            "first_candle_et": _iso(ordered[0]),
            "last_candle_et": _iso(ordered[-1]),
            "phase_candle_counts": phase_counts,
            "premarket_coverage": phase_counts["premarket"] > 0,
            "rth_coverage": phase_counts["rth"] > 0,
            "after_hours_coverage": phase_counts["after_hours"] > 0,
            "missing_intervals": gaps,
            "complete_for_premarket_and_rth_rvol": is_complete,
        }
        dates.append(record)
        (complete if is_complete else partial).append(day)

    start_day = datetime.fromtimestamp(requested_start_ms / 1000, tz=ET).date()
    end_day = datetime.fromtimestamp((requested_end_ms - 1) / 1000, tz=ET).date()
    weekdays, weekends = [], []
    cursor = start_day
    while cursor <= end_day:
        (weekends if cursor.weekday() >= 5 else weekdays).append(cursor.isoformat())
        cursor += timedelta(days=1)
    holidays = sorted(
        day.isoformat()
        for year in range(start_day.year, end_day.year + 1)
        for day in _nyse_full_holidays(year)
        if start_day <= day <= end_day
    )
    no_candles = sorted(set(weekdays) - set(grouped) - set(holidays))
    return {
        "symbol": symbol.upper(),
        "requested_start_et": _iso(requested_start_ms),
        "requested_end_et_exclusive": _iso(requested_end_ms),
        "receipt_timestamp_utc": receipt_timestamp,
        "returned_trading_dates": sorted(grouped),
        "distinct_complete_dates": complete,
        "distinct_complete_date_count": len(complete),
        "partial_dates": partial,
        "dates": dates,
        "excluded_weekends": weekends,
        "excluded_holidays": holidays,
        "excluded_weekdays_without_candles": no_candles,
        "weekday_exclusion_note": (
            "May be an exchange holiday or absent API data; the canary does not "
            "silently classify an absent weekday as a holiday."
        ),
        "api_response_metadata": {
            "empty": response.get("empty"),
            "response_symbol": response.get("symbol"),
            "candle_count": len(response.get("candles") or []),
            "out_of_requested_bounds_candle_count": out_of_bounds,
            "top_level_keys": sorted(str(key) for key in response),
            "frequency": "one_minute",
            "extended_hours_requested": True,
        },
        "requirement_met": len(complete) >= MINIMUM_COMPLETE_SESSIONS,
    }


def run_canary(
    *, symbols: list[str], cutoff_date: str, calendar_days: int,
    fetcher: Callable[[str, int, int, str], Mapping[str, Any]],
    rate_limit_seconds: float = 0.25,
) -> dict[str, Any]:
    cutoff = date.fromisoformat(cutoff_date)
    end = datetime.combine(cutoff, clock_time(0, 0), tzinfo=ET)
    start = end - timedelta(days=calendar_days)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    reports = []
    for index, symbol in enumerate(sorted({value.strip().upper() for value in symbols if value.strip()})):
        if index and rate_limit_seconds > 0:
            time.sleep(rate_limit_seconds)
        response = fetcher(symbol, start_ms, end_ms, "1m")
        received = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        reports.append(analyze_response(
            symbol=symbol, response=response, requested_start_ms=start_ms,
            requested_end_ms=end_ms, receipt_timestamp=received,
        ))
    proven = bool(reports) and all(item["requirement_met"] for item in reports)
    return {
        "schema_version": 1,
        "kind": "schwab_one_minute_extended_hours_retention_canary",
        "cutoff_date_exclusive": cutoff_date,
        "minimum_complete_sessions": MINIMUM_COMPLETE_SESSIONS,
        "symbols": reports,
        "automatic_history_requirement_proven": proven,
        "decision": (
            "enrollment_backfill_may_be_implemented"
            if proven else
            "automatic_backfill_blocked; use a rolling daily universe recorder"
        ),
    }


def _iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=ET).isoformat()


def _nyse_full_holidays(year: int) -> set[date]:
    """NYSE full-day closures used only for canary coverage accounting."""
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_sunday(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(_observed(date(year, 6, 19)))
    return holidays


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    day = date(year, month, 1)
    shift = (weekday - day.weekday()) % 7
    return day + timedelta(days=shift + (occurrence - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    day = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return day - timedelta(days=(day.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Schwab minute-history retention canary")
    parser.add_argument("output", type=Path)
    parser.add_argument("--symbols", required=True, help="comma-separated corpus symbols")
    parser.add_argument("--cutoff-date", required=True, help="exclusive ET date; current session is never requested")
    parser.add_argument("--calendar-days", type=int, default=50)
    parser.add_argument("--rate-limit-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)
    if args.calendar_days < 35:
        raise ValueError("--calendar-days must be at least 35 to contain 20 trading sessions")
    provider = TokenProvider()
    client = SchwabRestClient(
        base_url="https://api.schwabapi.com/trader/v1",
        auth_token_provider=provider,
    )
    result = run_canary(
        symbols=args.symbols.split(","), cutoff_date=args.cutoff_date,
        calendar_days=args.calendar_days, fetcher=client.fetch_price_history,
        rate_limit_seconds=args.rate_limit_seconds,
    )
    _atomic_write(args.output, result)
    return 0 if result["automatic_history_requirement_proven"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
