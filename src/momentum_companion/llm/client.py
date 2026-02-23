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
        self._http = httpx.Client(timeout=10.0)

    def complete(self, messages: list[dict[str, str]], model_override: str | None = None) -> Dict[str, Any]:
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

    def list_models(self) -> list[str]:
        resp = self._http.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", [])
        ids = [m.get("id") for m in models if m.get("id")]
        ids.sort()
        return ids
