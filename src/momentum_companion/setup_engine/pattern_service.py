from __future__ import annotations

from collections import deque
from dataclasses import asdict, is_dataclass
from threading import RLock
from typing import Any, Mapping

from momentum_companion.setup_engine.pattern_engine import PatternEngine
from momentum_companion.setup_engine.patterns import build_default_pattern_engine


class PatternEvaluationService:
    """Source-agnostic rolling evaluator for live and replay completed bars.

    This service knows nothing about Schwab, recorder file formats, UI, execution,
    or clocks. Any source capable of supplying completed bars can use the same
    interface.
    """

    def __init__(
        self,
        *,
        engine: PatternEngine | None = None,
        max_bars_per_symbol: int = 600,
    ) -> None:
        if max_bars_per_symbol <= 0:
            raise ValueError("max_bars_per_symbol must be positive")
        self.engine = engine or build_default_pattern_engine()
        self.max_bars_per_symbol = max_bars_per_symbol
        self._bars: dict[str, deque[dict[str, Any]]] = {}
        self._observations: dict[str, list[dict[str, Any]]] = {}
        self._status: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        return str(symbol or "").strip().upper()

    @staticmethod
    def _bar_dict(bar: Any) -> dict[str, Any]:
        if is_dataclass(bar):
            return asdict(bar)
        if isinstance(bar, Mapping):
            return dict(bar)
        raise TypeError("bar must be a dataclass or mapping")

    def update_security_status(self, symbol: str, status: str | None, ts_ms: int | None) -> dict[str, Any]:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            raise ValueError("symbol is required")
        normalized_status = str(status or "UNKNOWN").upper()
        ts_value = int(ts_ms) if ts_ms is not None else None
        with self._lock:
            current = dict(self._status.get(normalized) or {})
            previous = current.get("status")
            if normalized_status == "HALTED" and previous != "HALTED":
                current["halted_since_ms"] = ts_value
                current["last_halt_start_ms"] = ts_value
            elif previous == "HALTED" and normalized_status != "HALTED":
                current["last_resume_ms"] = ts_value
                current["halted_since_ms"] = None
            current["status"] = normalized_status
            current["updated_at_ms"] = ts_value
            self._status[normalized] = current
            return dict(current)

    def status_context(self, symbol: str) -> dict[str, Any]:
        normalized = self._normalize_symbol(symbol)
        with self._lock:
            return dict(self._status.get(normalized) or {"status": "UNKNOWN"})

    def ingest_completed_bar(self, symbol: str, bar: Any) -> list[dict[str, Any]]:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            raise ValueError("symbol is required")

        value = self._bar_dict(bar)
        with self._lock:
            bars = self._bars.setdefault(
                normalized, deque(maxlen=self.max_bars_per_symbol)
            )
            bars.append(value)
            observations = self.engine.detect_dicts(normalized, list(bars))
            status = dict(self._status.get(normalized) or {"status": "UNKNOWN"})
            for observation in observations:
                evidence = dict(observation.get("evidence") or {})
                evidence["trading_status"] = status.get("status", "UNKNOWN")
                evidence["halt_context"] = {
                    "halted_since_ms": status.get("halted_since_ms"),
                    "last_halt_start_ms": status.get("last_halt_start_ms"),
                    "last_resume_ms": status.get("last_resume_ms"),
                }
                observation["evidence"] = evidence
            self._observations[normalized] = observations
            return [dict(item) for item in observations]

    def seed_bars(self, symbol: str, bars) -> list[dict[str, Any]]:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            raise ValueError("symbol is required")

        materialized = [self._bar_dict(bar) for bar in bars]
        with self._lock:
            window = deque(materialized[-self.max_bars_per_symbol :], maxlen=self.max_bars_per_symbol)
            self._bars[normalized] = window
            observations = self.engine.detect_dicts(normalized, list(window))
            self._observations[normalized] = observations
            return [dict(item) for item in observations]

    def observations(self, symbol: str) -> list[dict[str, Any]]:
        normalized = self._normalize_symbol(symbol)
        with self._lock:
            return [dict(item) for item in self._observations.get(normalized, [])]

    def bars(self, symbol: str) -> list[dict[str, Any]]:
        normalized = self._normalize_symbol(symbol)
        with self._lock:
            return [dict(item) for item in self._bars.get(normalized, ())]

    def reset(self, symbol: str | None = None) -> None:
        with self._lock:
            if symbol is None:
                self._bars.clear()
                self._observations.clear()
                self._status.clear()
                return
            normalized = self._normalize_symbol(symbol)
            self._bars.pop(normalized, None)
            self._observations.pop(normalized, None)
            self._status.pop(normalized, None)
