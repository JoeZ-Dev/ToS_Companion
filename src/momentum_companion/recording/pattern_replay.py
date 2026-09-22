from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from momentum_companion.clients.stream_mapping import LevelOneCache
from momentum_companion.data.bar_aggregator import BarAggregator10s, TenSecondBar
from momentum_companion.data.price_update import PriceUpdate
from momentum_companion.setup_engine.pattern_service import PatternEvaluationService


class PatternReplayRunner:
    """Replay recorded L1 events through the same quote/bar/pattern semantics as live.

    Input records are the JSON objects written by MarketDayRecorder. This runner is
    intentionally headless and does not sleep or simulate wall-clock time; event
    timestamps carried by the recording drive aggregation deterministically.
    """

    def __init__(
        self,
        *,
        pattern_service: PatternEvaluationService | None = None,
    ) -> None:
        self.pattern_service = pattern_service or PatternEvaluationService()
        self._caches: dict[str, LevelOneCache] = {}
        self._aggregators: dict[str, BarAggregator10s] = {}
        self.completed_bars: dict[str, list[dict[str, Any]]] = {}
        self.pattern_updates: list[dict[str, Any]] = []

    def reset(self) -> None:
        self._caches.clear()
        self._aggregators.clear()
        self.completed_bars.clear()
        self.pattern_updates.clear()
        self.pattern_service.reset()

    @staticmethod
    def _symbol(record: Mapping[str, Any]) -> str:
        return str(record.get("symbol") or "").strip().upper()

    def feed_record(self, record: Mapping[str, Any]) -> list[dict[str, Any]]:
        if record.get("kind") != "market_event":
            return []
        if record.get("service") != "LEVELONE_EQUITIES":
            return []

        symbol = self._symbol(record)
        raw = record.get("raw")
        stream_ts_ms = record.get("stream_ts_ms")
        if not symbol or not isinstance(raw, Mapping) or stream_ts_ms is None:
            return []

        cache = self._caches.setdefault(symbol, LevelOneCache())
        message = {
            "service": "LEVELONE_EQUITIES",
            "timestamp": int(stream_ts_ms),
            "content": [dict(raw)],
        }
        event = cache.process_message(message)
        if event is None or event.get("last") is None:
            return []

        aggregator = self._aggregators.setdefault(symbol, BarAggregator10s())
        completed = aggregator.ingest_price(
            PriceUpdate(
                timestamp=int(event["ts_ms"] // 1000),
                price=float(event["last"]),
                size=event.get("volume"),
                source="L1",
            )
        )
        if completed is None:
            return []

        bar_dict = self._bar_dict(completed)
        self.completed_bars.setdefault(symbol, []).append(bar_dict)
        patterns = self.pattern_service.ingest_completed_bar(symbol, completed)
        update = {
            "symbol": symbol,
            "bar": bar_dict,
            "patterns": patterns,
        }
        self.pattern_updates.append(update)
        return patterns

    def replay_records(self, records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        for record in records:
            self.feed_record(record)
        return self.snapshot()

    def replay_file(self, path: str | Path) -> dict[str, Any]:
        source = Path(path)
        with source.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                self.feed_record(json.loads(line))
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        symbols = sorted(set(self.completed_bars) | set(self._aggregators))
        return {
            "symbols": {
                symbol: {
                    "completed_bars": [
                        dict(bar) for bar in self.completed_bars.get(symbol, [])
                    ],
                    "patterns": self.pattern_service.observations(symbol),
                }
                for symbol in symbols
            },
            "pattern_updates": [
                {
                    "symbol": item["symbol"],
                    "bar": dict(item["bar"]),
                    "patterns": [dict(pattern) for pattern in item["patterns"]],
                }
                for item in self.pattern_updates
            ],
        }

    @staticmethod
    def _bar_dict(bar: TenSecondBar) -> dict[str, Any]:
        return {
            "ts": bar.ts,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "is_extended": bar.is_extended,
            "stale": bar.stale,
        }
