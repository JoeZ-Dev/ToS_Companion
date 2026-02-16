from __future__ import annotations

from typing import Any

from momentum_companion.gates import TradingGateState, evaluate_gate
from momentum_companion.clients.reconciliation import reconcile_orders
from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


class GateEnforcer:
    """Enforces trading gate based on auth/stream/journal/reconciliation/quote freshness."""

    def __init__(self, rest_client: Any, stream_client: Any) -> None:
        self._rest = rest_client
        self._stream = stream_client

    def check_gate(self, account_hash: str, local_orders: dict, journal_healthy: bool, auth_ok: bool, now_ms: int) -> TradingGateState:
        broker_orders = self._rest.get_orders(account_hash)
        recon = reconcile_orders(local_orders, broker_orders)
        gate = evaluate_gate(
            auth_ok=auth_ok,
            stream_client=self._stream,
            journal_healthy=journal_healthy,
            reconciliation_complete=recon.gate_open,
            now_ms=now_ms,
        )
        if not recon.gate_open:
            logger.warning("Gate closed due to unknown working orders")
        return gate
