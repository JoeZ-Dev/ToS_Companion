from __future__ import annotations

import os
from typing import Any, Dict

import httpx
from httpx import HTTPStatusError

from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI chat completions client with mock mode."""

    def __init__(self, api_key: str, model: str, mode: str = "live") -> None:
        self._api_key = api_key
        self._model = model
        self._mode = mode
        # Allow a bit more headroom for larger prompts/responses
        self._http = httpx.Client(timeout=30.0)

    def complete(self, messages: list[dict[str, str]], model_override: str | None = None) -> Dict[str, Any]:
        if self._mode == "mock":
            return {
                "validity": "VALID_FOR_TRADING",
                "stock_bias": "HAS_POTENTIAL",
                "summary": "Mock response",
                "setups": [
                    {
                        "name": "Breakout",
                        "setup_state": "READY",
                        "trigger_condition": "break 10.5",
                        "entry_trigger_price": 10.5,
                        "stop_price": 10.0,
                        "target_price": 11.5,
                        "rr_to_target1": 2.0,
                        "move_pct_to_target1": 9.52,
                        "setup_rating": "B",
                        "confirmation_requirements": "volume expansion",
                        "target1_label": "nearest_resistance",
                        "extension_trigger": "",
                        "extension_target": "",
                        "extension_notes": "",
                        "tape_warning": "",
                    }
                ],
                "reason_codes": ["FAILED_BREAKOUT"],
            }
        resp = self._http.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": model_override or self._model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 800,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        return resp.json()

    def list_models(self) -> list[dict[str, Any]]:
        resp = self._http.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", [])
        return models
