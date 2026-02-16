from __future__ import annotations

from typing import Optional, Callable

from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


def refresh_and_reconnect(stream_client: Any, token_provider: Any, active_symbol: Optional[str]) -> None:
    """Refresh token and reconnect stream, then resubscribe to active symbol."""
    try:
        token_provider.refresh({})
    except Exception as exc:  # noqa: BLE001
        logger.error("Token refresh failed: %s", exc)
    try:
        stream_client.connect()
        if active_symbol:
            stream_client.subscribe_level_one(active_symbol)
    except Exception as exc:  # noqa: BLE001
        logger.error("Stream reconnect failed: %s", exc)
