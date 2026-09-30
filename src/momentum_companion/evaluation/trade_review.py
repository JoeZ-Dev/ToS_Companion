from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from momentum_companion.evaluation.momentum_eligibility import unavailable_eligibility
from momentum_companion.review import ReviewCorpus

RESULT_FILENAMES = ("counterfactual-results.json", "holdout-results.json")
DETECTOR_TOOLTIP = "Detector transition only. This does not imply a trade."


class TradeReviewStore:
    """Read-only adapter over deterministic research artifacts and recordings."""
    def __init__(self, root: Path | None, review_corpus: ReviewCorpus) -> None:
        self.root = Path(root).resolve() if root else None
        self.review_corpus = review_corpus

    def runs(self) -> dict[str, Any]:
        runs = []
        for run_id, path in self._run_paths():
            data = self._load(path)
            runs.append({"run_id": run_id, "kind": data.get("kind"),
                "classification": data.get("classification"), "code_revision": data.get("code_revision"),
                "opportunity_count": len(data.get("opportunities") or []), "artifact": path.name})
        return {"available": bool(runs), "configured_root": str(self.root) if self.root else None,
            "empty_state": None if runs else "No research artifacts are configured. Set TOS_RESEARCH_OUTPUT_DIR to a read-only counterfactual or holdout output directory.",
            "runs": runs}

    def opportunities(self, *, run_id: str, trading_date: str | None = None,
        symbol: str | None = None, policy: str = "confirmed_detector_stop",
        outcome: str | None = None, eligibility: str | None = None) -> dict[str, Any]:
        rows = []
        for item in self._run(run_id).get("opportunities") or []:
            if trading_date and item.get("trading_date") != trading_date: continue
            if symbol and str(item.get("symbol", "")).upper() != symbol.upper(): continue
            result = (item.get("policy_results") or {}).get(policy) or {"available": False, "reason": "policy_not_present", "legs": []}
            leg = _first_trade(result)
            row_outcome, momentum = _outcome(result, leg), _eligibility(item, policy, leg)
            if outcome and row_outcome != outcome: continue
            if eligibility and momentum["classification"] != eligibility: continue
            rows.append({"opportunity_id": item.get("opportunity_id"), "session_id": item.get("session_id"),
                "trading_date": item.get("trading_date"), "symbol": item.get("symbol"),
                "review_ts_ms": item.get("review_ts_ms"), "pattern": ", ".join(item.get("pattern_types") or []),
                "pattern_types": item.get("pattern_types") or [], "policy": policy,
                "policy_outcome": row_outcome, "realized_r": leg.get("realized_r") if leg else None,
                "eligibility": momentum["classification"], "human_label": item.get("human_label")})
        rows.sort(key=lambda row: (str(row["trading_date"]), str(row["symbol"]), int(row["review_ts_ms"] or 0), str(row["opportunity_id"])))
        return {"run_id": run_id, "policy": policy, "count": len(rows), "opportunities": rows}

    def detail(self, run_id: str, opportunity_id: str) -> dict[str, Any]:
        item = deepcopy(self._opportunity(run_id, opportunity_id)); policies = item.get("policy_results") or {}
        baseline = policies.get("production_baseline") or {"available": False, "legs": []}
        confirmed = policies.get("confirmed_detector_stop") or {"available": False, "legs": []}
        bleg, cleg = _first_trade(baseline), _first_trade(confirmed)
        item["paired_comparison"] = _paired_detail(baseline, confirmed, bleg, cleg)
        item["eligibility"] = _eligibility(item, "confirmed_detector_stop", cleg)
        item["outcomes"] = {name: _outcome_detail(result, _first_trade(result)) for name, result in sorted(policies.items())}
        return item

    def paired(self, run_id: str) -> dict[str, Any]:
        data = self._run(run_id)
        return deepcopy(data.get("paired_production_vs_confirmed_detector_stop") or data.get("paired_selection_and_execution") or {"overall": {}, "by_date": [], "by_symbol": []})

    def eligibility(self, run_id: str, opportunity_id: str) -> dict[str, Any]:
        item = self._opportunity(run_id, opportunity_id)
        result = (item.get("policy_results") or {}).get("confirmed_detector_stop") or {}
        return _eligibility(item, "confirmed_detector_stop", _first_trade(result))

    def chart(self, run_id: str, opportunity_id: str) -> dict[str, Any]:
        item = self._opportunity(run_id, opportunity_id); policies = item.get("policy_results") or {}
        baseline = _first_trade(policies.get("production_baseline") or {})
        confirmed = _first_trade(policies.get("confirmed_detector_stop") or {})
        times = [int(item.get("review_ts_ms") or 0)]
        for leg in (baseline, confirmed):
            if leg: times += [int(leg[key]) for key in ("entry_ts_ms", "exit_ts_ms") if leg.get(key)]
        try:
            packet = self.review_corpus.window(str(item["session_id"]), str(item["symbol"]),
                start_ms=min(times) - 600_000, end_ms=max(times) + 60_000)
            bars = packet.get("bars_10s") or []; availability = packet.get("window", {}).get("availability", {})
        except (ValueError, RuntimeError):
            bars, availability = [], {"status": "recording_unavailable"}
        markers = [{"kind": "detector_transition", "time_ms": int(item.get("review_ts_ms") or 0),
            "position": "aboveBar", "shape": "arrowDown", "color": "#67d2ff", "label": str(pattern),
            "accessible_label": f"{pattern}. {DETECTOR_TOOLTIP}", "tooltip": DETECTOR_TOOLTIP, "order": index}
            for index, pattern in enumerate(item.get("pattern_types") or [])]
        durations = []
        for policy, leg, color in (("production_baseline", baseline, "#f4c95d"), ("confirmed_detector_stop", confirmed, "#78e08f")):
            if not leg: continue
            markers += [_trade_marker("entry", policy, leg["entry_ts_ms"], color, "belowBar", "arrowUp"),
                _trade_marker("exit", policy, leg["exit_ts_ms"], color, "aboveBar", "circle")]
            durations.append({"policy": policy, "start_ms": leg.get("entry_ts_ms"), "end_ms": leg.get("exit_ts_ms"),
                "color": color, "accessible_label": f"{policy} trade duration"})
        primary, levels = confirmed or baseline, []
        if primary:
            for kind, key, color in (("initial_stop", "stop_price", "#ff6b6b"), ("target", "target_price", "#5ee6a8")):
                if primary.get(key) is not None: levels.append({"kind": kind, "price": primary[key], "color": color,
                    "label": kind.replace("_", " ").title(), "accessible_label": f"{kind.replace('_', ' ')} at {primary[key]}"})
        return {"run_id": run_id, "opportunity_id": opportunity_id, "availability": availability,
            "candles": bars, "markers": sorted(markers, key=lambda v: (v["time_ms"], v["kind"], v["label"])),
            "price_levels": levels, "trade_durations": durations, "detector_marker_disclaimer": DETECTOR_TOOLTIP}

    def _run_paths(self):
        if self.root is None or not self.root.is_dir(): return []
        paths = []
        for filename in RESULT_FILENAMES:
            if (self.root / filename).is_file(): paths.append(self.root / filename)
            paths.extend(self.root.glob(f"*/{filename}"))
        unique = sorted(set(path.resolve() for path in paths), key=str)
        return [("root" if path.parent == self.root else path.parent.name, path) for path in unique]

    def _run(self, run_id):
        matches = dict(self._run_paths())
        if run_id not in matches: raise ValueError(f"research run not found: {run_id}")
        return self._load(matches[run_id])

    def _opportunity(self, run_id, opportunity_id):
        for item in self._run(run_id).get("opportunities") or []:
            if item.get("opportunity_id") == opportunity_id: return item
        raise ValueError(f"opportunity not found: {opportunity_id}")

    @staticmethod
    def _load(path): return json.loads(path.read_text(encoding="utf-8"))


def _first_trade(result): return next((dict(leg) for leg in result.get("legs") or [] if leg.get("status") == "TRADE"), None)
def _outcome(result, leg): return str(leg.get("exit_reason") or "TRADE") if leg else ("UNAVAILABLE" if not result.get("available") else "SKIPPED")


def _outcome_detail(result, leg):
    if not leg: return {"entered": False, "available": bool(result.get("available")), "reason": result.get("reason")}
    keys = ("entry_price", "entry_ts_ms", "stop_price", "target_price", "exit_price", "exit_ts_ms", "exit_reason", "realized_r", "realized_pct", "mfe_r", "mae_r")
    return {"entered": True, "available": True, **{key: leg.get(key) for key in keys},
        "trade_duration_ms": int(leg["exit_ts_ms"]) - int(leg["entry_ts_ms"])}


def _paired_detail(baseline, confirmed, bleg, cleg):
    both = bleg is not None and cleg is not None
    delta = float(cleg["realized_r"]) - float(bleg["realized_r"]) if both else None
    decomposition = "delayed_entry_execution_effect" if both else ("selection_effect_baseline_only" if bleg else ("selection_effect_confirmed_only" if cleg else "neither_traded"))
    return {"baseline_entered": bleg is not None, "confirmed_entered": cleg is not None,
        "baseline": _outcome_detail(baseline, bleg), "confirmed": _outcome_detail(confirmed, cleg),
        "paired_r_delta": delta, "decomposition": decomposition}


def _eligibility(item, policy, leg):
    stored = (item.get("momentum_eligibility") or {}).get(policy)
    if isinstance(stored, Mapping): return deepcopy(dict(stored))
    decision = int((leg or {}).get("decision_ts_ms") or item.get("review_ts_ms") or 0)
    return unavailable_eligibility(decision_ts_ms=decision,
        reason="artifact does not contain the 20 prior-session cumulative-volume baseline and complete point-in-time resistance registry")


def _trade_marker(kind, policy, timestamp, color, position, shape):
    title = policy.replace("_", " ")
    return {"kind": kind, "time_ms": int(timestamp), "position": position, "shape": shape, "color": color,
        "label": f"{title} {kind}", "accessible_label": f"{title} {kind} marker", "tooltip": f"{title} {kind}"}
