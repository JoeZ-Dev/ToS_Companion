from __future__ import annotations

from typing import Any, Dict


class AnalysisEngineClient:
    """Invokes AE-1.0 for historical profile and AE-1.1 for live snapshots."""

    def run_historical_profile(self, symbol: str, datasets: Dict[str, Any]) -> Dict[str, Any]:
        """Compute AE-1.0 market profile; datasets keyed by timeframe."""
        raise NotImplementedError

    def run_live_snapshot(self, symbol: str, live_context: Dict[str, Any]) -> Dict[str, Any]:
        """Compute AE-1.1 snapshot on each completed 10s bar."""
        raise NotImplementedError
