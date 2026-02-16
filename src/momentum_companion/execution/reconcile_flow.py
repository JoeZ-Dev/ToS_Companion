from __future__ import annotations

from typing import Any, Dict

from momentum_companion.clients.reconciliation import reconcile_orders
from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


def check_unknown_working(rest_client: Any, account_hash: str, local_orders: Dict[str, Any], symbol: str | None = None) -> bool:
    """
    Fetch broker orders and return True if gate can open (no unknown working orders for current symbol).
    """
    broker_orders = rest_client.get_orders(account_hash)
    result = reconcile_orders(local_orders, broker_orders, symbol=symbol)
    if not result.gate_open:
        logger.warning("Unknown working orders detected; gate closed")
    return result.gate_open
