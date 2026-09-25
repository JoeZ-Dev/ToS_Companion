from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable


HORIZONS_SECONDS = (60, 300, 900)


@dataclass(frozen=True)
class StrengthPoint:
    ts_ms: int
    price: float


class RelativeStrengthTracker:
    """Cross-watchlist momentum context using only observed live prices.

    This is intentionally not RSI and not a trading signal. It answers:
    "which watched symbol has actually appreciated the most over comparable
    recent windows?" History starts when the runtime observes a symbol.
    """

    def __init__(self, *, retention_seconds: int = 1800) -> None:
        self.retention_ms = int(retention_seconds * 1000)
        self._points: dict[str, deque[StrengthPoint]] = {}
        self._halted: set[str] = set()

    def ingest(self, symbol: str, ts_ms: int, price: float) -> None:
        key = str(symbol or "").strip().upper()
        if not key or price <= 0:
            return
        points = self._points.setdefault(key, deque())
        if points and ts_ms < points[-1].ts_ms:
            return
        if points and ts_ms == points[-1].ts_ms:
            points[-1] = StrengthPoint(int(ts_ms), float(price))
        else:
            points.append(StrengthPoint(int(ts_ms), float(price)))
        cutoff = int(ts_ms) - self.retention_ms
        while len(points) > 1 and points[1].ts_ms < cutoff:
            points.popleft()

    def set_halted(self, symbol: str, halted: bool) -> None:
        key = str(symbol or "").strip().upper()
        if not key:
            return
        if halted:
            self._halted.add(key)
        else:
            self._halted.discard(key)

    @staticmethod
    def _return_pct(points: deque[StrengthPoint], now_ms: int, horizon_sec: int) -> float | None:
        if len(points) < 2:
            return None
        target = int(now_ms) - int(horizon_sec * 1000)
        baseline = None
        for point in points:
            if point.ts_ms <= target:
                baseline = point
            else:
                break
        if baseline is None or baseline.price <= 0:
            return None
        current = points[-1]
        return (current.price - baseline.price) / baseline.price * 100.0

    def snapshot(self, symbols: Iterable[str] | None = None) -> dict[str, dict]:
        keys = (
            [str(s).strip().upper() for s in symbols if str(s).strip()]
            if symbols is not None
            else sorted(self._points)
        )
        result: dict[str, dict] = {}
        for key in keys:
            points = self._points.get(key)
            if not points:
                result[key] = {
                    "halted": key in self._halted,
                    "return_1m_pct": None,
                    "return_5m_pct": None,
                    "return_15m_pct": None,
                    "rank_5m": None,
                    "watchlist_size_ranked": 0,
                    "leader_5m": False,
                }
                continue
            now_ms = points[-1].ts_ms
            result[key] = {
                "halted": key in self._halted,
                "return_1m_pct": self._return_pct(points, now_ms, 60),
                "return_5m_pct": self._return_pct(points, now_ms, 300),
                "return_15m_pct": self._return_pct(points, now_ms, 900),
                "rank_5m": None,
                "watchlist_size_ranked": 0,
                "leader_5m": False,
            }

        ranked = [
            (key, value["return_5m_pct"])
            for key, value in result.items()
            if value["return_5m_pct"] is not None and not value.get("halted")
        ]
        ranked.sort(key=lambda item: item[1], reverse=True)
        ranked_size = len(ranked)
        for rank, (key, value) in enumerate(ranked, start=1):
            result[key]["rank_5m"] = rank
            result[key]["watchlist_size_ranked"] = ranked_size
            result[key]["leader_5m"] = rank == 1 and ranked_size >= 2
            result[key]["relative_to_leader_5m_pct"] = (
                value - ranked[0][1] if ranked else None
            )
        return result

    def reset(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._points.clear()
            self._halted.clear()
            return
        key = str(symbol).strip().upper()
        self._points.pop(key, None)
        self._halted.discard(key)
