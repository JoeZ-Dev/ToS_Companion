from __future__ import annotations

from typing import Any, Dict

from momentum_companion.data.reason_codes import allowed_reason_codes
from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


class LLMCoach:
    """Handles LLM prompt assembly, invocation gating, and schema validation (§11)."""

    def __init__(self) -> None:
        # System prompt foundation; appended with structure awareness guidance.
        self.system_prompt = (
            "You are the LLM Coach for a momentum day-trading assistant.\n"
            "Longs only. Advisory only; never place/modify/cancel orders.\n"
            "Output must follow the expected JSON schema; no markdown.\n"
            "\n"
            "STRUCTURE AWARENESS RULES\n"
            "Use AE structural context when proposing entries and targets.\n"
            "Key signals available in the snapshot:\n"
            "- structure_context.next_resistance_distance_pct\n"
            "- volume_structure.volume_state\n"
            "- derived.distance_to_vwap_pct\n"
            "- micro.micro_state\n"
            "Apply these guidelines:\n"
            "1) Avoid entries directly under resistance. If structure_context.next_resistance_distance_pct < 0.4%, treat the setup as low probability unless it is a breakout through that level.\n"
            "2) Require expansion room. Momentum entries should generally have at least ~1% room to the next resistance cluster unless the trade specifically targets a breakout.\n"
            "3) Prefer continuation setups when volume_state is EXPANSION or HEALTHY_PULLBACK. Avoid setups when volume_state indicates DISTRIBUTION.\n"
            "4) Prefer setups when price is not heavily extended from VWAP. If derived.distance_to_vwap_pct > 4–5%, treat continuation entries cautiously.\n"
            "5) If no setup meets the above conditions, return NO_EDGE rather than forcing a trade.\n"
            "Additional guardrails:\n"
            "- If structure_context.next_resistance_distance_pct is not null and < 0.4, only propose breakout-through-resistance with hold/retest confirmation, otherwise return NO_EDGE. Do not propose targets within 0.4% of entry unless returning NO_EDGE.\n"
            "- If volume_structure.volume_state == DISTRIBUTION, cap setup_rating at B- and require hold/retest confirmation. If volume_state in {EXPANSION, HEALTHY_PULLBACK}, allow normal rating logic.\n"
            "- If derived.distance_to_vwap_pct is not null and > 0.05 (5%), entries must be pullback/retest based (no chase/buy-now).\n"
            "- You MUST select setups only from candidate_setups provided in the payload. Copy entry/stop/target/target1_label exactly from the chosen candidate. Include candidate_index (integer) in each setup referencing its candidate. If none are acceptable, return stock_bias=NO_EDGE and setups=[]. You may only adjust narrative fields and rating.\n"
            "- Each returned setup MUST include candidate_index and reference exactly one item from candidate_setups. Numeric fields must match the chosen candidate exactly.\n"
        )

    def run(self, snapshot_payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke the LLM with normalized payload when gated status/data_quality are ok."""
        if snapshot_payload.get("status") != "ok" or snapshot_payload.get("data_quality") != "ok":
            return {"validity": "NOT_VALID_FOR_TRADING", "reason_codes": ["DATA_STALE"]}
        # TODO: integrate actual LLM call and schema validation
        raise NotImplementedError

    @staticmethod
    def validate_response(resp: Dict[str, Any]) -> bool:
        """Validate reason_codes vocabulary per specs."""
        rcodes = resp.get("reason_codes", [])
        return all(code in allowed_reason_codes() for code in rcodes)
