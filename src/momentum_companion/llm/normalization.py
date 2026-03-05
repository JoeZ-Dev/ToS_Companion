from __future__ import annotations

from typing import Any, Dict

from momentum_companion.data.llm_contracts import LlmSnapshotPayload


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
    payload["bars_window"] = bars
    if "derived" in raw_snapshot:
        payload["derived"] = raw_snapshot.get("derived")
    if "volume_structure" in raw_snapshot:
        payload["volume_structure"] = raw_snapshot.get("volume_structure")
    if "structure_context" in raw_snapshot:
        payload["structure_context"] = raw_snapshot.get("structure_context")
    return payload  # type: ignore[return-value]
