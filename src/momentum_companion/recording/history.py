from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _minute_floor_ms(ts_ms: int) -> int:
    return (int(ts_ms) // 60_000) * 60_000


def _manifest_matches(
    manifest: dict,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> bool:
    symbols = {str(s).strip().upper() for s in manifest.get("symbols") or []}
    if symbol.upper() not in symbols:
        return False
    if "LEVELONE_EQUITIES" not in set(manifest.get("services") or []):
        return False

    started = manifest.get("started_at_et")
    if not started:
        return True
    try:
        started_dt = datetime.fromisoformat(str(started))
        if started_dt.tzinfo is None:
            started_dt = started_dt.replace(tzinfo=ET)
        started_ms = int(started_dt.timestamp() * 1000)
    except Exception:
        return True

    ended = manifest.get("ended_at_et")
    if ended:
        try:
            ended_dt = datetime.fromisoformat(str(ended))
            if ended_dt.tzinfo is None:
                ended_dt = ended_dt.replace(tzinfo=ET)
            ended_ms = int(ended_dt.timestamp() * 1000)
        except Exception:
            ended_ms = end_ms
    else:
        ended_ms = end_ms

    return started_ms <= end_ms and ended_ms >= start_ms


def load_recorded_minute_candles(
    symbol: str,
    start_ms: int,
    end_ms: int,
    *,
    root: Path | None = None,
) -> list[dict]:
    """Reconstruct 1-minute candles from persisted LEVELONE_EQUITIES evidence.

    Raw L1 stream messages are delta-oriented, so this carries forward the
    latest trade/last price and computes volume from cumulative total-volume
    changes. Returned candles use the same keys as Schwab pricehistory.

    This is intended as a gap-filler when Schwab REST history is unavailable;
    callers should prefer Schwab candles on timestamp collisions.
    """
    recordings_root = root or (Path.home() / ".tos_companion" / "recordings")
    normalized = str(symbol).strip().upper()
    if not normalized or not recordings_root.exists():
        return []

    rows: list[tuple[int, dict]] = []
    for manifest_path in sorted(recordings_root.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not _manifest_matches(
            manifest,
            symbol=normalized,
            start_ms=start_ms,
            end_ms=end_ms,
        ):
            continue

        event_path = manifest_path.parent / f"{normalized}.jsonl"
        if not event_path.exists():
            continue
        try:
            with event_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if record.get("service") != "LEVELONE_EQUITIES":
                        continue
                    ts_ms = record.get("stream_ts_ms")
                    raw = record.get("raw")
                    if ts_ms is None or not isinstance(raw, dict):
                        continue
                    ts_i = int(ts_ms)
                    if ts_i < start_ms or ts_i > end_ms:
                        continue
                    rows.append((ts_i, raw))
        except OSError:
            continue

    if not rows:
        return []

    rows.sort(key=lambda item: item[0])
    last_price: float | None = None
    last_cum_volume: float | None = None
    bars: dict[int, dict] = {}

    for ts_ms, raw in rows:
        raw_price = raw.get("3")
        if raw_price is not None:
            try:
                last_price = float(raw_price)
            except (TypeError, ValueError):
                pass

        volume_delta = 0.0
        raw_volume = raw.get("8")
        if raw_volume is not None:
            try:
                cumulative = float(raw_volume)
            except (TypeError, ValueError):
                cumulative = None
            if cumulative is not None:
                if last_cum_volume is not None and cumulative >= last_cum_volume:
                    volume_delta = cumulative - last_cum_volume
                last_cum_volume = cumulative

        if last_price is None:
            continue

        minute_ms = _minute_floor_ms(ts_ms)
        bar = bars.get(minute_ms)
        if bar is None:
            bars[minute_ms] = {
                "datetime": minute_ms,
                "open": last_price,
                "high": last_price,
                "low": last_price,
                "close": last_price,
                "volume": volume_delta,
            }
            continue

        bar["high"] = max(float(bar["high"]), last_price)
        bar["low"] = min(float(bar["low"]), last_price)
        bar["close"] = last_price
        bar["volume"] = float(bar.get("volume") or 0.0) + volume_delta

    return [bars[key] for key in sorted(bars)]


def merge_candles_prefer_primary(
    primary: Iterable[dict],
    fallback: Iterable[dict],
) -> list[dict]:
    """Merge candle sets by datetime, preferring primary on collisions."""
    merged: dict[int, dict] = {}
    for candle in fallback:
        ts = candle.get("datetime")
        if ts is not None:
            merged[int(ts)] = dict(candle)
    for candle in primary:
        ts = candle.get("datetime")
        if ts is not None:
            merged[int(ts)] = dict(candle)
    return [merged[key] for key in sorted(merged)]
