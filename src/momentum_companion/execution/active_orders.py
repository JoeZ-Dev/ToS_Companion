from __future__ import annotations

from typing import Dict, Any


class ActiveOrdersTracker:
    """Tracks active orders keyed by broker orderId."""

    def __init__(self) -> None:
        self._orders: Dict[str, Dict[str, Any]] = {}

    def upsert(self, order_id: str, info: Dict[str, Any]) -> None:
        self._orders[order_id] = info

    def remove(self, order_id: str) -> None:
        self._orders.pop(order_id, None)

    def list_ids(self) -> list[str]:
        return list(self._orders.keys())
