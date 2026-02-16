from __future__ import annotations

import os
from typing import Any, Dict

import httpx

from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI chat completions client with mock mode."""

    def __init__(self, api_key: str, model: str, mode: str = "live") -> None:
        self._api_key = api_key
        self._model = model
        self._mode = mode
        self._http = httpx.Client(timeout=10.0)

    def complete(self, messages: list[dict[str, str]]) -> Dict[str, Any]:
        if self._mode == "mock":
            return {
                "validity": "VALID_FOR_TRADING",
                "setup_rating": "B",
                "entry_price": 10.0,
                "stop_loss": 9.5,
                "target_price": 12.0,
                "risk_reward": 4.0,
                "summary": "Mock response",
                "reason_codes": ["FAILED_BREAKOUT"],
            }
        resp = self._http.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self._model, "messages": messages, "response_format": {"type": "json_object"}},
        )
        resp.raise_for_status()
        return resp.json()
