from __future__ import annotations

from typing import Any, Dict

from momentum_companion.data.llm_contracts import LlmSnapshotPayload

def _aggregate_1m_to_5m(bars_1m: list[dict]) -> list[dict]:
    """Aggregate 1m bars into compact 5m bars without UI dependency."""
    if not isinstance(bars_1m, list):
        return []
    cleaned = []
    for b in bars_1m:
        if not isinstance(b, dict):
            continue
        ts = b.get("ts_ms") or b.get("ts") or b.get("t")
        o = b.get("o") if "o" in b else b.get("open")
        h = b.get("h") if "h" in b else b.get("high")
        l = b.get("l") if "l" in b else b.get("low")
        c = b.get("c") if "c" in b else b.get("close")
        v = b.get("v") if "v" in b else b.get("volume")
        if ts is None or o is None or h is None or l is None or c is None or v is None:
            continue
        try:
            cleaned.append({"ts_ms": int(ts), "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v)})
        except Exception:
            continue
    cleaned = sorted(cleaned, key=lambda x: x["ts_ms"])
    buckets: dict[int, dict] = {}
    for b in cleaned:
        bucket_start = (int(b["ts_ms"]) // 300_000) * 300_000
        bucket = buckets.get(bucket_start)
        if bucket is None:
            buckets[bucket_start] = {
                "ts_ms": bucket_start,
                "o": b["o"],
                "h": b["h"],
                "l": b["l"],
                "c": b["c"],
                "v": b["v"],
            }
        else:
            bucket["h"] = max(bucket["h"], b["h"])
            bucket["l"] = min(bucket["l"], b["l"])
            bucket["c"] = b["c"]
            bucket["v"] += b["v"]
    return [buckets[k] for k in sorted(buckets.keys())]


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
    built_from_1m = False
    if (not bars or len(bars) == 0) and isinstance(bars_1m, list) and len(bars_1m) >= 5:
        bars = _aggregate_1m_to_5m(bars_1m)
        built_from_1m = True
    payload["bars_window"] = bars
    if bars_1m:
        payload["bars_1m"] = bars_1m
    if built_from_1m:
        payload["bars_5m_built_from_1m"] = True
    if "derived" in raw_snapshot:
        payload["derived"] = raw_snapshot.get("derived")
    if "levels" in raw_snapshot:
        payload["levels"] = raw_snapshot.get("levels")
    if "micro" in raw_snapshot:
        payload["micro"] = raw_snapshot.get("micro")
    if "session" in raw_snapshot:
        payload["session"] = raw_snapshot.get("session")
    if "vwap" in raw_snapshot:
        payload["vwap"] = raw_snapshot.get("vwap")
    if "volume_structure" in raw_snapshot:
        payload["volume_structure"] = raw_snapshot.get("volume_structure")
    if "structure_context" in raw_snapshot:
        payload["structure_context"] = raw_snapshot.get("structure_context")
    if raw_snapshot.get("candidate_setups") is not None:
        payload["candidate_setups"] = raw_snapshot.get("candidate_setups")
    if raw_snapshot.get("candidate_hints") is not None:
        payload["candidate_hints"] = raw_snapshot.get("candidate_hints")
    breakout = _compute_breakout_targets(payload)
    if breakout:
        payload.update(breakout)
    return payload  # type: ignore[return-value]


def _compute_breakout_targets(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute deterministic breakout trigger/targets for LLM context:
    - nearest_breakout_trigger: nearest_resistance.price (only if meaningfully above price)
    - next_structural_target_above_trigger: next higher structural high above trigger (skip trivial <=0.2% gaps)
    - second_structural_target_above_trigger: second higher structural high above trigger
    """
    out: Dict[str, Any] = {}
    levels = snapshot.get("levels") or {}
    trigger = None
    try:
        nr = levels.get("nearest_resistance") if isinstance(levels, dict) else None
        if isinstance(nr, dict) and nr.get("price") is not None:
            trigger = float(nr.get("price"))
    except Exception:
        trigger = None
    if trigger is None:
        return out
    current_price = None
    quote = snapshot.get("quote") or {}
    try:
        current_price = float(quote.get("last"))
    except Exception:
        current_price = None
    # require trigger meaningfully above current price
    if current_price is not None and trigger <= current_price * 1.002:
        return out
    candidates: list[float] = []
    session = snapshot.get("session") or {}
    micro = snapshot.get("micro") or {}
    for val in [
        session.get("opening_range_high") if isinstance(session, dict) else None,
        session.get("premarket_high") if isinstance(session, dict) else None,
        micro.get("micro_resistance_15m") if isinstance(micro, dict) else None,
    ]:
        try:
            f = float(val)
            candidates.append(f)
        except Exception:
            continue
    bars = snapshot.get("bars_window") or []
    for b in bars:
        if not isinstance(b, dict):
            continue
        try:
            h = float(b.get("h"))
            candidates.append(h)
        except Exception:
            continue
    higher = sorted({c for c in candidates if c > trigger * 1.002})
    out["nearest_breakout_trigger"] = trigger
    if higher:
        out["next_structural_target_above_trigger"] = higher[0]
    if len(higher) > 1:
        out["second_structural_target_above_trigger"] = higher[1]
    return out
