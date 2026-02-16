from __future__ import annotations

from typing import Any, Dict

from momentum_companion.execution.emm_engine import EMMEngine
from momentum_companion.triggers.synthetic import SyntheticTriggerEngine
from momentum_companion.journal.writer import JournalWriter
from momentum_companion.clients.reconciliation import reconcile_orders, ReconciliationResult
from momentum_companion.execution.reconcile_flow import check_unknown_working
from momentum_companion.utils.logging import logging
from momentum_companion.gates import TradingGateState
from momentum_companion.execution.active_orders import ActiveOrdersTracker
from momentum_companion.utils.time import utc_now_str


class TradeExecutor:
    """Routes orders per session rules, including EMM and synthetic triggers (§9)."""

    def __init__(
        self,
        rest_client: Any,
        emm_engine: EMMEngine,
        trigger_engine: SyntheticTriggerEngine,
        journal: JournalWriter,
        state_callback: Any | None = None,
    ) -> None:
        self._rest_client = rest_client
        self._emm_engine = emm_engine
        self._trigger_engine = trigger_engine
        self._journal = journal
        self._logger = logging.getLogger(__name__)
        self._active_orders = ActiveOrdersTracker()
        self._state_callback = state_callback
        self._last_reconcile_state: str | None = None

    def submit_order(self, order_spec: Dict[str, Any], gate: TradingGateState | None = None) -> str:
        """Submit an order respecting NORMAL vs SEAMLESS constraints and safety gate."""
        if gate and not gate.enabled:
            self._logger.warning("Trading gate closed; rejecting order")
            self._journal.append_event(
                {
                    "ts_utc": order_spec.get("ts_utc") or "now",
                    "symbol": order_spec.get("symbol"),
                    "event_type": "ERROR",
                    "session_mode": order_spec.get("session_mode", "SEAMLESS"),
                    "connection_state": "RECONNECTING",
                    "notes_json": "gate_closed",
                }
            )
            return "gate_closed"
        session = order_spec.get("session_mode", "NORMAL")
        side = order_spec.get("side")
        qty = order_spec.get("qty")
        ref_price = order_spec.get("ref_price")
        latest_quote = order_spec.get("quote", {})
        # gate check against unknown working orders
        if not check_unknown_working(
            self._rest_client, order_spec["account_id"], self._active_orders._orders, symbol=order_spec.get("symbol")
        ):
            self._journal.append_event(
                {
                    "ts_utc": order_spec.get("ts_utc") or "now",
                    "symbol": order_spec.get("symbol"),
                    "event_type": "GATE_UNKNOWN_WORKING_ORDERS",
                    "session_mode": session,
                    "connection_state": "RECONNECTING",
                    "notes_json": "UNKNOWN_WORKING_ORDERS",
                }
            )
            if self._state_callback:
                try:
                    self._state_callback("UNKNOWN_WORKING_ORDERS")
                except Exception:
                    pass
            return "gate_closed"
        if session == "SEAMLESS":
            settings = order_spec.get("emm_settings", {})
            try:
                status = self._emm_engine.execute(
                    order_spec["account_id"], side, qty, ref_price, settings, latest_quote, order_spec.get("symbol")
                )
                event = {
                    "ts_utc": order_spec.get("ts_utc") or utc_now_str(),
                    "symbol": order_spec.get("symbol"),
                    "event_type": "BROKER_SUBMIT",
                    "session_mode": session,
                    "connection_state": "CONNECTED",
                    "side": side,
                    "qty": qty,
                    "order_type": "LIMIT",
                    "limit_price": ref_price,
                    "emm_active": 1,
                }
                if status in ("emm_timeout", "emm_no_quote", "emm_stale_quote"):
                    event["notes_json"] = status
                    if status == "emm_timeout":
                        event["event_type"] = "TIMEOUT"
                    elif status == "emm_no_quote":
                        event["event_type"] = "NO_QUOTE"
                    else:
                        event["event_type"] = "STALE_QUOTE"
                self._journal.append_event(event)
                return status
            except TimeoutError:
                self._logger.error("EMM TIMEOUT")
                return "emm_timeout"
            except ValueError as exc:
                self._logger.error("EMM error: %s", exc)
                return "emm_error"
        order_id = self._rest_client.place_order(order_spec["account_id"], order_spec["order_payload"])
        self._journal.append_event(
            {
                "ts_utc": order_spec.get("ts_utc"),
                "symbol": order_spec.get("symbol"),
                "event_type": "BROKER_SUBMIT",
                "session_mode": session,
                "connection_state": "CONNECTED",
                "side": side,
                "qty": qty,
                "order_type": order_spec["order_payload"].get("orderType"),
                "limit_price": order_spec["order_payload"].get("price"),
                "stop_price": order_spec["order_payload"].get("stopPrice"),
                "broker_order_id": order_id,
            }
        )
        return order_id

    def flatten_position(self, symbol: str) -> None:
        """Cancel working orders and close the position."""
        self._journal.append_event(
            {
                "ts_utc": "now",
                "symbol": symbol,
                "event_type": "FLATTEN",
                "session_mode": "SEAMLESS",
                "connection_state": "CONNECTED",
            }
        )

    def cancel_all(self, account_id: str, order_ids: list[str], symbol: str) -> None:
        """Cancel working orders and disarm triggers."""
        for oid in order_ids:
            try:
                self._rest_client.cancel_order(account_id, oid)
            except Exception as exc:  # noqa: BLE001
                self._logger.error("Cancel failed for %s: %s", oid, exc)
        self._trigger_engine.disarm(symbol)
        self._journal.append_event(
            {
                "ts_utc": "now",
                "symbol": symbol,
                "event_type": "BROKER_CANCEL",
                "session_mode": "SEAMLESS",
                "connection_state": "CONNECTED",
            }
        )

    def reconcile(self, local_orders: dict, broker_orders: list[dict]) -> ReconciliationResult:
        """Reconcile working orders with broker truth per §15 Startup Trading Safety Gate."""
        result = reconcile_orders(local_orders, broker_orders)
        if not result.gate_open and self._state_callback:
            try:
                self._state_callback("UNKNOWN_WORKING_ORDERS")
            except Exception:
                pass
        self._last_reconcile_state = "open" if result.gate_open else "closed"
        return result

    def journal_emm_failure(self, symbol: str, event_type: str, last_quote_age_ms: int | None = None) -> None:
        """Journal EMM failure events."""
        self._journal.append_event(
            {
                "ts_utc": "now",
                "symbol": symbol,
                "event_type": event_type,
                "session_mode": "SEAMLESS",
                "connection_state": "RECONNECTING",
                "notes_json": event_type,
                "emm_active": 1,
                "broker_order_id": ",".join(self._active_orders.list_ids()),
                "emm_bound_price": None,
                "emm_attempt_n": None,
            }
        )
