from __future__ import annotations

from typing import Any, Dict, List

from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


class ReconciliationResult:
    def __init__(self, unknown_working: List[Dict[str, Any]]) -> None:
        self.unknown_working = unknown_working

    @property
    def gate_open(self) -> bool:
        return len(self.unknown_working) == 0


def reconcile_orders(local_orders: Dict[str, Any], broker_orders: List[Dict[str, Any]], symbol: str | None = None) -> ReconciliationResult:
    """
    Compare local working orders to broker truth; flag unknowns for active symbol.
    broker_orders expected shape: list of order dicts including orderId, status, symbol.
    """
    broker_by_id = {str(o.get("orderId")): o for o in broker_orders}
    unknown = []
    for order in broker_orders:
        oid = str(order.get("orderId"))
        if symbol and order.get("symbol") != symbol:
            continue
        if oid not in local_orders:
            unknown.append(order)
    # gate remains closed if unknown working orders exist
    return ReconciliationResult(unknown_working=unknown)
