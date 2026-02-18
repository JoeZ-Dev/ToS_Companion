from __future__ import annotations

from typing import Dict, Optional

from momentum_companion.data.contracts import QuoteEvent


# bid/ask/last/volume are required to emit per Appendix D rules.
REQUIRED_FIELDS = ("bid", "ask", "last", "volume")


class LevelOneCache:
    """Maintains last-known fields and emits canonical quote events per Appendix D."""

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, float]] = {}

    def process_message(self, message: dict) -> Optional[QuoteEvent]:
        """
        Map a LEVELONE_EQUITIES message to a QuoteEvent.
        Returns None if required fields are still missing after applying the delta.
        Raises ValueError on schema violations.
        """
        try:
            service = message.get("service")
            if service != "LEVELONE_EQUITIES":
                return None
            ts_raw = message.get("timestamp")
            if ts_raw is None:
                return None
            ts_ms = int(ts_raw)
            content_list = message.get("content") or []
            if not content_list:
                return None
            content = content_list[0]
            symbol = content.get("key")
            if not symbol:
                return None
        except Exception:
            return None

        fields = content
        sym_cache = self._cache.setdefault(symbol, {})

        mapping = {
            "bid": fields.get("1"),
            "ask": fields.get("2"),
            "last": fields.get("3"),
            "bid_size": fields.get("4"),
            "ask_size": fields.get("5"),
            "last_size": None,  # not present in captured payload
            "volume": fields.get("8"),
        }

        for key, val in mapping.items():
            if val is not None:
                sym_cache[key] = float(val)

        if not all(k in sym_cache for k in REQUIRED_FIELDS):
            return None

        return QuoteEvent(
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
