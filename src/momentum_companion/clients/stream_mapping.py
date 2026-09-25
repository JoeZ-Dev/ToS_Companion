from __future__ import annotations

from typing import Any, Dict, Optional

from momentum_companion.data.contracts import QuoteEvent


# bid/ask/last are required for UI + aggregation; volume may be absent after-hours.
REQUIRED_FIELDS = ("bid", "ask", "last")


class LevelOneCache:
    """Maintains last-known fields and emits canonical quote events per Appendix D."""

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}

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
            numeric_mapping = {
                "bid": fields.get("1"),
                "ask": fields.get("2"),
                "last": fields.get("3"),
                "bid_size": fields.get("4"),
                "ask_size": fields.get("5"),
                "volume": fields.get("8"),
                "last_size": fields.get("9"),
                "hard_to_borrow_quantity": fields.get("46"),
                "hard_to_borrow_rate": fields.get("47"),
            }
            for key, val in numeric_mapping.items():
                if val is not None:
                    sym_cache[key] = float(val)

            if fields.get("32") is not None:
                sym_cache["security_status"] = str(fields.get("32"))
            if fields.get("48") is not None:
                raw_htb = int(fields.get("48"))
                sym_cache["hard_to_borrow"] = None if raw_htb < 0 else bool(raw_htb)
            if fields.get("49") is not None:
                raw_shortable = int(fields.get("49"))
                sym_cache["shortable"] = None if raw_shortable < 0 else bool(raw_shortable)
            if fields.get("34") is not None:
                sym_cache["quote_time_ms"] = int(fields.get("34"))
            if fields.get("35") is not None:
                sym_cache["trade_time_ms"] = int(fields.get("35"))

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
                    security_status=sym_cache.get("security_status"),
                    hard_to_borrow_quantity=sym_cache.get("hard_to_borrow_quantity"),
                    hard_to_borrow_rate=sym_cache.get("hard_to_borrow_rate"),
                    hard_to_borrow=sym_cache.get("hard_to_borrow"),
                    shortable=sym_cache.get("shortable"),
                    quote_time_ms=sym_cache.get("quote_time_ms"),
                    trade_time_ms=sym_cache.get("trade_time_ms"),
                )
            )
        return events

    def process_message(self, message: dict) -> Optional[QuoteEvent]:
        """Backward-compatible single-event mapper."""
        events = self.process_messages(message)
        return events[0] if events else None
