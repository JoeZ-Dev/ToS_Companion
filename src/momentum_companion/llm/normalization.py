from __future__ import annotations

from typing import Any, Dict

from momentum_companion.data.llm_contracts import LlmSnapshotPayload
from momentum_companion.setup_engine.candidate_generator import generate_candidate_setups


def normalize_snapshot(raw_snapshot: Dict[str, Any], session_mode: str, quote: Dict[str, Any]) -> LlmSnapshotPayload:
    """
    Normalize AE-1.1 snapshot into the LLM payload per specs.md §11.2.5.
    - map bars_window_5m -> bars_window
    - append schema_version, session_mode, quote
    """
    payload: Dict[str, Any] = {}
    payload["schema_version"] = "AE-1.1"
    payload["status"] = raw_snapshot.get("status")
    payload["data_quality"] = raw_snapshot.get("data_quality")
    payload["as_of_ts_ms"] = raw_snapshot.get("as_of_ts_ms")
    payload["symbol"] = raw_snapshot.get("symbol")
    payload["session_mode"] = session_mode
    payload["quote"] = {
        "bid": quote.get("bid"),
        "ask": quote.get("ask"),
        "last": quote.get("last"),
        "volume": quote.get("volume"),
    }
    payload["market_state"] = raw_snapshot.get("market_state")
    bars = raw_snapshot.get("bars_window_5m", [])
    bars_1m = raw_snapshot.get("bars_1m") or []
    if (not bars or len(bars) == 0) and isinstance(bars_1m, list) and len(bars_1m) >= 5:
        from momentum_companion.ui.controller import aggregate_1m_to_5m  # avoid circular import issues

        bars = aggregate_1m_to_5m(bars_1m)
    payload["bars_window"] = bars
    if bars_1m:
        payload["bars_1m"] = bars_1m
    if "derived" in raw_snapshot:
        payload["derived"] = raw_snapshot.get("derived")
    if "volume_structure" in raw_snapshot:
        payload["volume_structure"] = raw_snapshot.get("volume_structure")
    if "structure_context" in raw_snapshot:
        payload["structure_context"] = raw_snapshot.get("structure_context")
    if raw_snapshot.get("candidate_setups") is not None:
        payload["candidate_setups"] = raw_snapshot.get("candidate_setups")
    else:
        try:
            payload["candidate_setups"] = generate_candidate_setups(dict(payload))
        except Exception:
            payload["candidate_setups"] = []
    return payload  # type: ignore[return-value]
