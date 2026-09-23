from __future__ import annotations

from typing import Dict, Optional

from momentum_companion.data.contracts import QuoteEvent


# bid/ask/last are required for UI + aggregation; volume may be absent after-hours.
REQUIRED_FIELDS = ("bid", "ask", "last")


class LevelOneCache:
    """Maintains last-known fields and emits canonical quote events per Appendix D."""

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, float]] = {}

    def process_messages(self, message: dict) -> list[QuoteEvent]:
        """Map every symbol delta in one LEVELONE_EQUITIES message."""
        service = message.get("service")
        if service != "LEVELONE_EQUITIES":
            raise ValueError("Unsupported service")
        ts_raw = message.get("timestamp")
        if ts_raw is None:
            return []
        ts_ms = int(ts_raw)
        content_list = message.get("content") or []
        if not isinstance(content_list, list):
            return []

        events: list[QuoteEvent] = []
        for fields in content_list:
            if not isinstance(fields, dict):
                continue
            symbol = fields.get("key")
            if not symbol:
                continue

            sym_cache = self._cache.setdefault(symbol, {})
            mapping = {
                "bid": fields.get("1"),
                "ask": fields.get("2"),
                "last": fields.get("3"),
                "bid_size": fields.get("4"),
                "ask_size": fields.get("5"),
                "last_size": None,
                "volume": fields.get("8"),
            }
            for key, val in mapping.items():
                if val is not None:
                    sym_cache[key] = float(val)

            if not all(k in sym_cache for k in REQUIRED_FIELDS):
                continue

            events.append(
                QuoteEvent(
                    ts_ms=ts_ms,
                    symbol=symbol,
                    bid=sym_cache.get("bid"),
                    ask=sym_cache.get("ask"),
                    last=sym_cache.get("last"),
                    bid_size=sym_cache.get("bid_size"),
                    ask_size=sym_cache.get("ask_size"),
                    last_size=sym_cache.get("last_size"),
                    volume=sym_cache.get("volume"),
                    source_ts_type="QUOTE_TS",
                    raw_source="SCHWAB_STREAM",
                )
            )
        return events

    def process_message(self, message: dict) -> Optional[QuoteEvent]:
        """Backward-compatible single-event mapper."""
        events = self.process_messages(message)
        return events[0] if events else None
