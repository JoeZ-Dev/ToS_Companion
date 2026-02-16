from __future__ import annotations

from typing import Any, Dict

from momentum_companion.data.reason_codes import allowed_reason_codes
from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


class LLMCoach:
    """Handles LLM prompt assembly, invocation gating, and schema validation (§11)."""

    def __init__(self) -> None:
        pass

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
