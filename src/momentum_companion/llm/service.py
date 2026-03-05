from __future__ import annotations

from typing import Any, Dict

from momentum_companion.llm.coach import LLMCoach
from momentum_companion.llm.normalization import normalize_snapshot
from momentum_companion.llm.validator import (
    validate_llm_output,
    validate_llm_selected_candidates,
    validate_trade_setups,
)
from momentum_companion.llm.client import LLMClient
from momentum_companion.journal.writer import JournalWriter
from momentum_companion.utils.logging import logging


class LLMService:
    """Wrapper that normalizes snapshot, gates, and validates response."""

    def __init__(
        self,
        coach: LLMCoach,
        client: LLMClient | None = None,
        journal: JournalWriter | None = None,
        state_callback: Any | None = None,
        flash_callback: Any | None = None,
    ) -> None:
        self._coach = coach
        self._client = client
        self._journal = journal
        self._state_callback = state_callback
        self._flash_callback = flash_callback
        self._last_rec_by_symbol: Dict[str, Dict[str, Any]] = {}

    def evaluate(
        self,
        raw_snapshot: Dict[str, Any],
        session_mode: str,
        quote: Dict[str, Any],
        model_override: str | None = None,
        messages_override: list[dict] | None = None,
    ) -> Dict[str, Any]:
        payload = normalize_snapshot(raw_snapshot, session_mode, quote)
        logger = logging.getLogger(__name__)

        def _invoke(msgs: list[dict]) -> Dict[str, Any]:
            if self._client:
                return self._client.complete(msgs, model_override=model_override)
            return self._coach.run(payload, {})

        messages = messages_override or [
            {"role": "system", "content": "LLM Coach"},
            {"role": "user", "content": str(payload)},
        ]

        resp = _invoke(messages)
        if not self._coach.validate_response(resp):
            return {"validity": "NOT_VALID_FOR_TRADING", "reason_codes": ["LLM_SCHEMA_INVALID"]}
        if not validate_llm_output(resp):
            self._log_invalid(payload, session_mode)
            return {"validity": "NOT_VALID_FOR_TRADING", "reason_codes": ["LLM_SCHEMA_INVALID"]}

        resp, cand_valid, cand_reasons, cand_action = validate_llm_selected_candidates(payload, resp, retry_attempted=False)
        warnings: list[str] = list(cand_reasons)
        if cand_action == "RETRY":
            logger.info("LLM candidate selection invalid; retrying with repair prompt reasons=%s", cand_reasons)
            repair_messages = list(messages) + [
                {
                    "role": "system",
                    "content": "You must select from candidate_setups. Do not change numeric fields. If none fit, return NO_EDGE.",
                }
            ]
            resp = _invoke(repair_messages)
            if not self._coach.validate_response(resp) or not validate_llm_output(resp):
                self._log_invalid(payload, session_mode)
                return {"validity": "NOT_VALID_FOR_TRADING", "reason_codes": ["LLM_REPAIR_FAILED"], "stock_bias": "NO_EDGE", "setups": []}
            resp, cand_valid, cand_reasons, cand_action = validate_llm_selected_candidates(payload, resp, retry_attempted=True)
            warnings.extend(cand_reasons)
            if cand_action != "OK":
                return {"validity": "NOT_VALID_FOR_TRADING", "reason_codes": ["LLM_CANDIDATE_MISMATCH"], "stock_bias": "NO_EDGE", "setups": []}

        valid, reasons, action = validate_trade_setups(payload, resp, retry_attempted=False)
        if action == "RETRY":
            logger.info("LLM trade validation failed; retrying with repair prompt reasons=%s", reasons)
            repair_messages = list(messages) + [
                {
                    "role": "system",
                    "content": (
                        "Repair required: Your prior setup(s) had trivial targets. "
                        "Choose the next farther structural target (prefer swing_high from bars, then premarket_high, then opening_range_high, then micro_resistance_15m). "
                        "Do NOT output targets within 1.5% of entry unless you return NO_EDGE."
                    ),
                }
            ]
            resp = _invoke(repair_messages)
            if not self._coach.validate_response(resp) or not validate_llm_output(resp):
                self._log_invalid(payload, session_mode)
                return {"validity": "NOT_VALID_FOR_TRADING", "reason_codes": ["LLM_REPAIR_FAILED"], "stock_bias": "NO_EDGE", "setups": []}
            # ensure repair response still honors candidate selection
            resp, cand_valid2, cand_reasons2, cand_action2 = validate_llm_selected_candidates(payload, resp, retry_attempted=True)
            warnings.extend(cand_reasons2)
            if cand_action2 != "OK":
                return {"validity": "NOT_VALID_FOR_TRADING", "reason_codes": ["LLM_CANDIDATE_MISMATCH"], "stock_bias": "NO_EDGE", "setups": []}
            valid, reasons, action = validate_trade_setups(payload, resp, retry_attempted=True)
            if action != "OK":
                return {"validity": "NOT_VALID_FOR_TRADING", "reason_codes": ["LLM_REPAIR_TRADE_INVALID"], "stock_bias": "NO_EDGE", "setups": []}
            warnings.extend(reasons)
        else:
            warnings.extend(reasons)
        if warnings:
            resp["validation_warnings"] = warnings
        symbol = payload.get("symbol")
        if symbol:
            self._maybe_flash(symbol, resp, payload)
        return resp

    def _log_invalid(self, payload: Dict[str, Any], session_mode: str) -> None:
        if self._journal:
            self._journal.append_event(
                {
                    "ts_utc": payload.get("as_of_ts_ms"),
                    "symbol": payload.get("symbol"),
                    "event_type": "LLM_INVALID_OUTPUT",
                    "session_mode": session_mode,
                    "connection_state": "CONNECTED",
                    "notes_json": "LLM_INVALID_OUTPUT",
                }
            )
        if self._state_callback:
            try:
                self._state_callback("LLM_INVALID_OUTPUT")
            except Exception:
                pass

    def _maybe_flash(self, symbol: str, rec: Dict[str, Any], payload: Dict[str, Any]) -> None:
        """Apply flash rules per specs §11.4/§11.4.1."""
        prev = self._last_rec_by_symbol.get(symbol)
        flash = False
        if prev:
            # validity flip
            if prev.get("validity") != rec.get("validity"):
                flash = True
            # rating change >=2 notches
            if self._rating_delta(prev.get("setup_rating"), rec.get("setup_rating")) >= 2:
                flash = True
            # price changes >=0.5%
            for key in ("entry_price", "stop_loss", "target_price"):
                if self._pct_change(prev.get(key), rec.get(key)) >= 0.5:
                    flash = True
            # risk_reward drop below 2 from >=2
            if prev.get("risk_reward") is not None and rec.get("risk_reward") is not None:
                if prev.get("risk_reward") >= 2.0 and rec.get("risk_reward") < 2.0:
                    flash = True
            # reason codes severity high
            if any(code in {"ENTRY_APPROACHING", "STOP_THREAT", "HALT_OR_REJECT", "DISCONNECT", "EXECUTION_FILL", "RISK_BREACH"} for code in rec.get("reason_codes", [])):
                flash = True
            # in-position actions
            if rec.get("trade_management_action") in {"EXIT_NOW", "SCALE_OUT_50"}:
                flash = True
            if rec.get("action_urgency") == "HIGH":
                flash = True
        self._last_rec_by_symbol[symbol] = rec
        if flash and self._flash_callback:
            try:
                self._flash_callback(symbol, rec, payload)
            except Exception:
                pass

    @staticmethod
    def _rating_delta(prev: Any, current: Any) -> int:
        order = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D"]
        if prev not in order or current not in order:
            return 0
        return abs(order.index(prev) - order.index(current))

    @staticmethod
    def _pct_change(old: Any, new: Any) -> float:
        if old is None or new is None:
            return 0.0
        try:
            return abs((float(new) - float(old)) / float(old)) * 100
        except Exception:
            return 0.0
