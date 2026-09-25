from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


ENTRY_STATES = frozenset({"BREAKOUT", "CONTINUATION"})


@dataclass
class ExcursionRecord:
    pattern_id: str
    pattern_type: str
    entry_state: str
    entry_ts: int
    entry_price: float
    horizon_seconds: int
    bars_observed: int = 0
    lowest_price: float | None = None
    highest_price: float | None = None
    last_price: float | None = None
    last_ts: int | None = None
    closed: bool = False

    def update(self, bar: Any) -> None:
        low = float(getattr(bar, "low", bar.get("low") if isinstance(bar, dict) else self.entry_price))
        high = float(getattr(bar, "high", bar.get("high") if isinstance(bar, dict) else self.entry_price))
        close = float(getattr(bar, "close", bar.get("close") if isinstance(bar, dict) else self.entry_price))
        ts = int(getattr(bar, "ts", bar.get("ts", bar.get("time")) if isinstance(bar, dict) else self.entry_ts))
        self.lowest_price = low if self.lowest_price is None else min(self.lowest_price, low)
        self.highest_price = high if self.highest_price is None else max(self.highest_price, high)
        self.last_price = close
        self.last_ts = ts
        self.bars_observed += 1
        if ts - self.entry_ts >= self.horizon_seconds:
            self.closed = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mae_pct"] = (
            (self.lowest_price - self.entry_price) / self.entry_price * 100.0
            if self.lowest_price is not None and self.entry_price
            else None
        )
        payload["mfe_pct"] = (
            (self.highest_price - self.entry_price) / self.entry_price * 100.0
            if self.highest_price is not None and self.entry_price
            else None
        )
        payload["return_pct"] = (
            (self.last_price - self.entry_price) / self.entry_price * 100.0
            if self.last_price is not None and self.entry_price
            else None
        )
        return payload


class ReplayExcursionEvaluator:
    """Measure post-confirmation MAE/MFE without inventing an exit strategy.

    A record opens only on a transition into BREAKOUT/CONTINUATION. The bar
    that caused confirmation is the entry bar and is NOT used for excursion
    measurement, because its intrabar high/low occurred before the close where
    confirmation became known. Excursions begin with the following bar.
    """

    def __init__(self, *, horizon_seconds: int = 900) -> None:
        self.horizon_seconds = int(horizon_seconds)
        self._states: dict[str, str] = {}
        self._active: dict[str, ExcursionRecord] = {}
        self._completed: list[ExcursionRecord] = []

    def reset(self) -> None:
        self._states.clear()
        self._active.clear()
        self._completed.clear()

    def advance_bar(self, bar: Any) -> None:
        for pattern_id, record in list(self._active.items()):
            record.update(bar)
            if record.closed:
                self._completed.append(record)
                del self._active[pattern_id]

    def observe_patterns(self, patterns: Iterable[dict], *, bar_ts: int, close: float) -> None:
        seen_ids: set[str] = set()
        for pattern in patterns:
            pattern_id = str(pattern.get("id") or "")
            if not pattern_id:
                continue
            seen_ids.add(pattern_id)
            state = str(pattern.get("state") or "")
            previous = self._states.get(pattern_id)
            if state in ENTRY_STATES and previous not in ENTRY_STATES and pattern_id not in self._active:
                self._active[pattern_id] = ExcursionRecord(
                    pattern_id=pattern_id,
                    pattern_type=str(pattern.get("pattern_type") or "UNKNOWN"),
                    entry_state=state,
                    entry_ts=int(bar_ts),
                    entry_price=float(close),
                    horizon_seconds=self.horizon_seconds,
                )
            self._states[pattern_id] = state

        # Keep prior states for temporarily absent observations. Pattern IDs may
        # reappear as the rolling detector window evolves; forgetting them would
        # create duplicate "first confirmation" entries.

    def snapshot(self) -> dict[str, Any]:
        completed = [record.to_dict() for record in self._completed]
        active = [record.to_dict() for record in self._active.values()]
        combined = completed + active
        maes = [x["mae_pct"] for x in combined if x["mae_pct"] is not None]
        mfes = [x["mfe_pct"] for x in combined if x["mfe_pct"] is not None]
        return {
            "horizon_seconds": self.horizon_seconds,
            "signals": combined,
            "completed_count": len(completed),
            "active_count": len(active),
            "avg_mae_pct": sum(maes) / len(maes) if maes else None,
            "avg_mfe_pct": sum(mfes) / len(mfes) if mfes else None,
        }
