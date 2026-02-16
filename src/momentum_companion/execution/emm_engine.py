from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


class EMMEngine:
    """Implements chase-limit execution for SEAMLESS session per specs.md §9.3."""

    def __init__(self, rest_client: Any, journal: Any | None = None) -> None:
        self._rest_client = rest_client
        self._journal = journal

    def execute(
        self,
        account_id: str,
        side: str,
        qty: float,
        ref_price: float,
        settings: Dict[str, float],
        latest_quote: Dict[str, float],
        symbol: str | None = None,
    ) -> str:
        """
        Run the chase loop within slippage/interval/duration bounds.
        This is a skeleton; actual order submit/replace would call SchwabRestClient.
        """
        cap_pct = settings.get("emm_max_slippage_pct", 1.5) / 100.0
        interval_ms = int(settings.get("emm_chase_interval_ms", 250))
        max_duration_s = settings.get("emm_max_chase_duration_s", 3)
        start_ts = time.time()

        buy = side.upper() in ("BUY", "BUY_TO_COVER")
        cap = ref_price * (1 + cap_pct) if buy else ref_price * (1 - cap_pct)
        attempt = 0
        order_id: Optional[str] = None
        age_ms: Optional[int] = None
        while (time.time() - start_ts) <= max_duration_s:
            attempt += 1
            age_ms = latest_quote.get("age_ms")
            ts_ms = latest_quote.get("ts_ms")
            if age_ms is None and ts_ms is not None:
                age_ms = int(time.time() * 1000) - int(ts_ms)
            if age_ms is not None and age_ms > 5000:
                if order_id:
                    try:
                        self._rest_client.cancel_order(account_id, order_id)
                    except Exception:
                        pass
                self._journal_abort("STALE_QUOTE", symbol, [order_id] if order_id else [], age_ms, "stale_quote")
                return "emm_stale_quote"
            try:
                price = self._compute_price(buy, cap, latest_quote)
            except ValueError as exc:
                logger.error("EMM error: %s", exc)
                if order_id:
                    try:
                        self._rest_client.cancel_order(account_id, order_id)
                    except Exception:
                        pass
                self._journal_abort("NO_QUOTE", symbol, [order_id] if order_id else [], age_ms, str(exc))
                return "emm_no_quote"
            if order_id is None:
                order_payload = {
                    "orderType": "LIMIT",
                    "price": round(price, 2),
                    "session": "AM",
                    "orderStrategyType": "SINGLE",
                }
                order_id = self._rest_client.place_order(account_id, order_payload)
            else:
                replace_payload = {
                    "orderType": "LIMIT",
                    "price": round(price, 2),
                    "session": "AM",
                    "orderStrategyType": "SINGLE",
                }
                self._rest_client.replace_order(account_id, order_id, replace_payload)
            logger.info("EMM attempt %s at price %.2f qty %.2f", attempt, price, qty)
            time.sleep(interval_ms / 1000)
        if order_id:
            try:
                self._rest_client.cancel_order(account_id, order_id)
            except Exception:
                pass
        self._journal_abort("TIMEOUT", symbol, [order_id] if order_id else [], age_ms, "timeout")
        return "emm_timeout"

    @staticmethod
    def _compute_price(buy: bool, bound: float, quote: Dict[str, float]) -> float:
        if buy:
            ask = quote.get("ask")
            if ask is None:
                raise ValueError("EMM NO QUOTE")
            return min(ask, bound)
        bid = quote.get("bid")
        if bid is None:
            raise ValueError("EMM NO QUOTE")
        return max(bid, bound)

    def abort_disconnect(self, symbol: str, active_order_ids: list[str]) -> None:
        """Abort due to disconnect while EMM active."""
        self._journal_abort("DISCONNECT", symbol, active_order_ids, None, "disconnect")

    def _journal_abort(
        self, reason: str, symbol: str | None, active_order_ids: list[str], last_quote_age_ms: int | None, note: str
    ) -> None:
        if not self._journal:
            return
        payload = {
            "event_type": reason,
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "symbol": symbol or "",
            "session_mode": "SEAMLESS",
            "connection_state": "RECONNECTING",
            "notes_json": json.dumps(
                {
                    "active_order_ids": active_order_ids,
                    "last_quote_age_ms": last_quote_age_ms,
                    "note": note,
                    "emm_state": "active",
                }
            ),
            "broker_order_id": ",".join([oid for oid in active_order_ids if oid]),
            "emm_active": 1,
        }
        try:
            self._journal.append_event(payload)
        except Exception:
            logger.error("Failed to journal EMM abort")
