from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from momentum_companion.clients.schwab_rest import SchwabRestClient
from momentum_companion.clients.token_provider import TokenProvider

ET = ZoneInfo("America/New_York")
REPAIR_SOURCE = "SCHWAB_PRICEHISTORY_1M_GAP_REPAIR"
DEFAULT_MIN_GAP_SECONDS = 90


def _load_json_lines(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    tmp.replace(path)


def _market_event_timestamps(rows: list[dict[str, Any]], symbol: str) -> list[int]:
    normalized = symbol.upper()
    timestamps = {
        int(row["stream_ts_ms"])
        for row in rows
        if row.get("kind") == "market_event"
        and row.get("service") == "LEVELONE_EQUITIES"
        and str(row.get("symbol") or "").strip().upper() == normalized
        and row.get("stream_ts_ms") is not None
    }
    return sorted(timestamps)


def _gap_minutes(timestamps: list[int], *, min_gap_ms: int) -> tuple[set[int], list[dict[str, int]]]:
    missing: set[int] = set()
    gaps: list[dict[str, int]] = []
    if len(timestamps) < 2:
        return missing, gaps

    for previous, current in zip(timestamps, timestamps[1:]):
        gap_ms = current - previous
        if gap_ms <= min_gap_ms:
            continue
        previous_minute = (previous // 60_000) * 60_000
        current_minute = (current // 60_000) * 60_000
        minute = previous_minute + 60_000
        gap_count = 0
        while minute < current_minute:
            missing.add(minute)
            gap_count += 1
            minute += 60_000
        if gap_count:
            gaps.append(
                {
                    "after_ms": previous,
                    "before_ms": current,
                    "gap_ms": gap_ms,
                    "missing_minutes": gap_count,
                }
            )
    return missing, gaps


def _fetch_repair_candles(
    rest: Any,
    symbol: str,
    missing_minutes: set[int],
) -> list[dict[str, Any]]:
    if not missing_minutes:
        return []
    start_ms = min(missing_minutes)
    end_ms = max(missing_minutes) + 60_000
    response = rest.fetch_price_history(symbol, start_ms, end_ms, "1m")
    candles: list[dict[str, Any]] = []
    for candle in response.get("candles") or []:
        ts = candle.get("datetime")
        if ts is None:
            continue
        ts_i = int(ts)
        if ts_i not in missing_minutes:
            continue
        candles.append(
            {
                "datetime": ts_i,
                "open": candle.get("open"),
                "high": candle.get("high"),
                "low": candle.get("low"),
                "close": candle.get("close"),
                "volume": candle.get("volume") or 0,
            }
        )
    candles.sort(key=lambda value: int(value["datetime"]))
    return candles


def repair_recording_session(
    session_dir: Path,
    symbols: Iterable[str],
    rest: Any,
    *,
    min_gap_seconds: int = DEFAULT_MIN_GAP_SECONDS,
) -> dict[str, Any]:
    session_dir = Path(session_dir)
    manifest_path = session_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if manifest.get("kind") != "market_day_recording":
        raise ValueError("not a market-day recording")
    if not manifest.get("ended_at_et"):
        raise RuntimeError("recording session is still active; stop it before gap repair")

    allowed = {
        str(value).strip().upper()
        for value in manifest.get("symbols") or []
        if str(value).strip()
    }
    requested = []
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if symbol and symbol not in requested:
            requested.append(symbol)
    if not requested:
        raise ValueError("at least one symbol is required")

    unknown = [symbol for symbol in requested if symbol not in allowed]
    if unknown:
        raise ValueError(f"symbols not in recording: {', '.join(unknown)}")

    repairs = manifest.setdefault("gap_repairs", {})
    summary: dict[str, Any] = {"session": session_dir.name, "symbols": {}}
    min_gap_ms = max(1, int(min_gap_seconds)) * 1000

    for symbol in requested:
        canonical = session_dir / f"{symbol}.jsonl"
        backup = session_dir / f"{symbol}.jsonl.original"
        if not canonical.exists() and not backup.exists():
            summary["symbols"][symbol] = {"status": "missing_recording"}
            continue

        source = backup if backup.exists() else canonical
        original_rows = _load_json_lines(source)
        timestamps = _market_event_timestamps(original_rows, symbol)
        missing_minutes, gaps = _gap_minutes(timestamps, min_gap_ms=min_gap_ms)

        if not gaps:
            summary["symbols"][symbol] = {
                "status": "no_gap",
                "gaps": 0,
                "candles_inserted": 0,
            }
            continue

        candles = _fetch_repair_candles(rest, symbol, missing_minutes)
        if not backup.exists():
            shutil.copy2(canonical, backup)

        repair_rows = [
            {
                "schema_version": 1,
                "kind": "historical_candle",
                "symbol": symbol,
                "stream_ts_ms": int(candle["datetime"]),
                "source": REPAIR_SOURCE,
                "candle": candle,
            }
            for candle in candles
        ]

        combined: list[tuple[int, int, dict[str, Any]]] = []
        for index, row in enumerate(original_rows):
            ts = row.get("stream_ts_ms")
            sort_ts = int(ts) if ts is not None else 2**63 - 1
            combined.append((sort_ts, index * 2, row))
        for index, row in enumerate(repair_rows):
            combined.append((int(row["stream_ts_ms"]), index * 2 + 1, row))
        combined.sort(key=lambda item: (item[0], item[1]))
        _atomic_write_jsonl(canonical, [row for _, _, row in combined])

        repair_state = {
            "status": "complete",
            "source": REPAIR_SOURCE,
            "completed_at_et": datetime.now(ET).isoformat(),
            "original_file": backup.name,
            "canonical_file": canonical.name,
            "gap_threshold_seconds": int(min_gap_seconds),
            "gaps": gaps,
            "requested_missing_minutes": len(missing_minutes),
            "candles_inserted": len(candles),
            "first_repair_bar_et": (
                datetime.fromtimestamp(int(candles[0]["datetime"]) / 1000, tz=ET).isoformat()
                if candles
                else None
            ),
            "last_repair_bar_et": (
                datetime.fromtimestamp(int(candles[-1]["datetime"]) / 1000, tz=ET).isoformat()
                if candles
                else None
            ),
        }
        repairs[symbol] = repair_state
        summary["symbols"][symbol] = repair_state

    _atomic_write_json(manifest_path, manifest)
    return summary


def _latest_completed_session(root: Path) -> Path:
    candidates: list[tuple[datetime, Path]] = []
    for manifest_path in root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            ended = manifest.get("ended_at_et")
            if not ended:
                continue
            ended_dt = datetime.fromisoformat(str(ended))
            if ended_dt.tzinfo is None:
                ended_dt = ended_dt.replace(tzinfo=ET)
            candidates.append((ended_dt.astimezone(ET), manifest_path.parent))
        except Exception:
            continue
    if not candidates:
        raise RuntimeError("no completed recording session found")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair large gaps in a completed recording using Schwab 1-minute candles."
    )
    parser.add_argument(
        "--session",
        default="latest",
        help="Session directory name under ~/.tos_companion/recordings, or 'latest'.",
    )
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--min-gap-seconds", type=int, default=DEFAULT_MIN_GAP_SECONDS)
    args = parser.parse_args()

    root = Path.home() / ".tos_companion" / "recordings"
    session_dir = (
        _latest_completed_session(root)
        if args.session == "latest"
        else root / args.session
    )
    rest = SchwabRestClient(
        base_url="https://api.schwabapi.com/marketdata/v1",
        auth_token_provider=TokenProvider(),
    )
    summary = repair_recording_session(
        session_dir,
        args.symbols,
        rest,
        min_gap_seconds=args.min_gap_seconds,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
