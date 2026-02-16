from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TradingGateState:
    auth_ok: bool
    stream_connected: bool
    quote_fresh: bool
    journal_healthy: bool
    reconciliation_complete: bool

    @property
    def enabled(self) -> bool:
        return all(
            [
                self.auth_ok,
                self.stream_connected,
                self.quote_fresh,
                self.journal_healthy,
                self.reconciliation_complete,
            ]
        )


def evaluate_gate(
    auth_ok: bool,
    stream_client: Any,
    journal_healthy: bool,
    reconciliation_complete: bool,
    now_ms: int,
) -> TradingGateState:
    """Evaluate trading gate per specs §15."""
    stream_connected = stream_client.connection_state() == "CONNECTED"
    quote_fresh = stream_client.is_fresh(now_ms)
    return TradingGateState(
        auth_ok=auth_ok,
        stream_connected=stream_connected,
        quote_fresh=quote_fresh,
        journal_healthy=journal_healthy,
        reconciliation_complete=reconciliation_complete,
    )
