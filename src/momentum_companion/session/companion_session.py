from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import threading
import time
from typing import Any, Callable, Mapping

from momentum_companion.data.contracts import QuoteEvent
from momentum_companion.data.bar_aggregator import TenSecondBar


SessionSubscriber = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class SessionEvent:
    """Serializable event emitted by the headless application session."""

    sequence: int
    event_type: str
    emitted_at: float
    symbol: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "type": self.event_type,
            "emitted_at": self.emitted_at,
            "symbol": self.symbol,
            "payload": dict(self.payload),
        }


@dataclass
class _SymbolState:
    symbol: str
    quote: dict[str, Any] = field(
        default_factory=lambda: {
            "ts_ms": None,
            "bid": None,
            "ask": None,
            "last": None,
            "bid_size": None,
            "ask_size": None,
            "last_size": None,
            "volume": None,
            "source_ts_type": None,
            "raw_source": None,
        }
    )
    history_bars: list[dict[str, Any]] = field(default_factory=list)
    bars_10s: list[dict[str, Any]] = field(default_factory=list)
    ae_snapshot: dict[str, Any] | None = None
    llm_output: dict[str, Any] | None = None
    trade_state: dict[str, Any] | None = None
    pattern_observations: list[dict[str, Any]] = field(default_factory=list)


class CompanionSession:
    """Qt-free source of truth for live ToS_Companion application state.

    This class deliberately does not own Schwab authentication or OAuth tokens.
    It receives normalized market/application events from existing backend
    services and exposes browser-friendly snapshots/events.
    """

    def __init__(self, *, max_bars_per_symbol: int = 600) -> None:
        if max_bars_per_symbol <= 0:
            raise ValueError("max_bars_per_symbol must be positive")
        self._max_bars_per_symbol = max_bars_per_symbol
        self._symbols: dict[str, _SymbolState] = {}
        self._active_symbol: str | None = None
        self._connection_state = "DISCONNECTED"
        self._recorder_state: dict[str, Any] = {"active": False}
        self._sequence = 0
        self._subscribers: set[SessionSubscriber] = set()
        self._lock = threading.RLock()

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return symbol.strip().upper()

    def subscribe(self, subscriber: SessionSubscriber) -> Callable[[], None]:
        """Register an event subscriber and return an unsubscribe callback."""
        with self._lock:
            self._subscribers.add(subscriber)

        def unsubscribe() -> None:
            with self._lock:
                self._subscribers.discard(subscriber)

        return unsubscribe

    def watched_symbols(self) -> list[str]:
        with self._lock:
            return list(self._symbols)

    def add_symbol(self, symbol: str, *, make_active: bool = False) -> str:
        normalized = self.normalize_symbol(symbol)
        if not normalized:
            raise ValueError("symbol is required")

        created = False
        active_changed = False
        with self._lock:
            if normalized not in self._symbols:
                self._symbols[normalized] = _SymbolState(symbol=normalized)
                created = True
            if self._active_symbol is None or make_active:
                active_changed = self._active_symbol != normalized
                self._active_symbol = normalized

        if created:
            self._emit("symbol_added", symbol=normalized, payload={"symbol": normalized})
        if active_changed:
            self._emit(
                "active_symbol",
                symbol=normalized,
                payload={"symbol": normalized},
            )
        return normalized

    def remove_symbol(self, symbol: str) -> bool:
        normalized = self.normalize_symbol(symbol)
        if not normalized:
            return False

        next_active: str | None = None
        with self._lock:
            if normalized not in self._symbols:
                return False
            del self._symbols[normalized]
            if self._active_symbol == normalized:
                self._active_symbol = next(iter(self._symbols), None)
                next_active = self._active_symbol

        self._emit("symbol_removed", symbol=normalized, payload={"symbol": normalized})
        self._emit(
            "active_symbol",
            symbol=next_active,
            payload={"symbol": next_active},
        )
        return True

    def set_active_symbol(self, symbol: str) -> str:
        normalized = self.normalize_symbol(symbol)
        if not normalized:
            raise ValueError("symbol is required")
        with self._lock:
            if normalized not in self._symbols:
                raise KeyError(normalized)
            changed = self._active_symbol != normalized
            self._active_symbol = normalized
        if changed:
            self._emit("active_symbol", symbol=normalized, payload={"symbol": normalized})
        return normalized

    def update_connection_state(self, state: str) -> None:
        normalized = str(state or "UNKNOWN").upper()
        with self._lock:
            if normalized == self._connection_state:
                return
            self._connection_state = normalized
        self._emit("connection_state", payload={"state": normalized})

    def ingest_quote(self, quote: QuoteEvent | Mapping[str, Any]) -> None:
        symbol = self.normalize_symbol(str(quote.get("symbol") or ""))
        if not symbol:
            raise ValueError("quote symbol is required")
        self.add_symbol(symbol)

        update = {
            "ts_ms": quote.get("ts_ms"),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "last": quote.get("last"),
            "bid_size": quote.get("bid_size"),
            "ask_size": quote.get("ask_size"),
            "last_size": quote.get("last_size"),
            "volume": quote.get("volume"),
            "source_ts_type": quote.get("source_ts_type"),
            "raw_source": quote.get("raw_source"),
        }
        with self._lock:
            self._symbols[symbol].quote.update(update)
            payload = dict(self._symbols[symbol].quote)
        self._emit("quote", symbol=symbol, payload=payload)

    def set_history(self, symbol: str, bars: list[Mapping[str, Any]]) -> None:
        normalized = self.add_symbol(symbol)
        value = [dict(bar) for bar in bars]
        with self._lock:
            self._symbols[normalized].history_bars = value
        self._emit(
            "history",
            symbol=normalized,
            payload={"bars": value},
        )

    def ingest_bar(self, symbol: str, bar: TenSecondBar | Mapping[str, Any]) -> None:
        normalized = self.add_symbol(symbol)
        if is_dataclass(bar):
            bar_dict = asdict(bar)
        else:
            bar_dict = dict(bar)

        with self._lock:
            bars = self._symbols[normalized].bars_10s
            bars.append(bar_dict)
            if len(bars) > self._max_bars_per_symbol:
                del bars[: len(bars) - self._max_bars_per_symbol]
        self._emit("completed_bar", symbol=normalized, payload=bar_dict)

    def update_ae_snapshot(self, symbol: str, snapshot: Mapping[str, Any] | None) -> None:
        normalized = self.add_symbol(symbol)
        value = dict(snapshot) if snapshot is not None else None
        with self._lock:
            self._symbols[normalized].ae_snapshot = value
        self._emit("analysis_snapshot", symbol=normalized, payload={"snapshot": value})

    def update_llm_output(self, symbol: str, output: Mapping[str, Any] | None) -> None:
        normalized = self.add_symbol(symbol)
        value = dict(output) if output is not None else None
        with self._lock:
            self._symbols[normalized].llm_output = value
        self._emit("llm_update", symbol=normalized, payload={"output": value})

    def update_trade_state(self, symbol: str, state: Mapping[str, Any] | None) -> None:
        normalized = self.add_symbol(symbol)
        value = dict(state) if state is not None else None
        with self._lock:
            self._symbols[normalized].trade_state = value
        self._emit("trade_state", symbol=normalized, payload={"state": value})

    def update_pattern_observations(
        self,
        symbol: str,
        observations: list[Mapping[str, Any]],
    ) -> None:
        normalized = self.add_symbol(symbol)
        value = [dict(observation) for observation in observations]
        with self._lock:
            self._symbols[normalized].pattern_observations = value
        self._emit("pattern_update", symbol=normalized, payload={"patterns": value})

    def update_recorder_state(self, state: Mapping[str, Any]) -> None:
        value = dict(state)
        with self._lock:
            self._recorder_state = value
        self._emit("recorder_state", payload=value)

    def snapshot(self) -> dict[str, Any]:
        """Return a self-contained JSON-serializable application snapshot."""
        with self._lock:
            symbols = {
                symbol: {
                    "symbol": state.symbol,
                    "quote": dict(state.quote),
                    "history_bars": [dict(bar) for bar in state.history_bars],
                    "bars_10s": [dict(bar) for bar in state.bars_10s],
                    "ae_snapshot": (
                        dict(state.ae_snapshot) if state.ae_snapshot is not None else None
                    ),
                    "llm_output": (
                        dict(state.llm_output) if state.llm_output is not None else None
                    ),
                    "trade_state": (
                        dict(state.trade_state) if state.trade_state is not None else None
                    ),
                    "pattern_observations": [
                        dict(observation) for observation in state.pattern_observations
                    ],
                }
                for symbol, state in self._symbols.items()
            }
            return {
                "connection_state": self._connection_state,
                "active_symbol": self._active_symbol,
                "watched_symbols": list(self._symbols),
                "recorder_state": dict(self._recorder_state),
                "symbols": symbols,
                "sequence": self._sequence,
            }

    def _emit(
        self,
        event_type: str,
        *,
        symbol: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._sequence += 1
            event = SessionEvent(
                sequence=self._sequence,
                event_type=event_type,
                emitted_at=time.time(),
                symbol=symbol,
                payload=dict(payload or {}),
            ).as_dict()
            subscribers = tuple(self._subscribers)

        # Never allow a UI/WebSocket subscriber failure to interrupt market-data state.
        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception:
                continue
