from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from momentum_companion.utils.logging import logging
from momentum_companion.utils.errors import map_http_error
from momentum_companion.utils.backoff import with_backoff

logger = logging.getLogger(__name__)


class SchwabRestClient:
    """REST client wrapper for Schwab endpoints (accounts/orders/history) per specs.md §13."""

    def __init__(
        self,
        base_url: str,
        auth_token_provider: Any,
        timeout: float = 10.0,
        client: Optional[httpx.Client] = None,
        marketdata_base_url: Optional[str] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._md_base_url = (marketdata_base_url or "https://api.schwabapi.com/marketdata/v1").rstrip("/")
        self._auth_token_provider = auth_token_provider
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def _headers(self) -> Dict[str, str]:
        token = self._auth_token_provider()
        return {"Authorization": f"Bearer {token}"}

    @with_backoff()
    def get_accounts(self) -> Dict[str, Any]:
        """Fetch linked accounts and balances."""
        resp = self._request("GET", f"{self._base_url}/accounts")
        return resp.json()

    @with_backoff()
    def place_order(self, account_id: str, order_payload: Dict[str, Any]) -> str:
        """Submit an order and return the broker order id."""
        try:
            resp = self._request(
                "POST",
                f"{self._base_url}/accounts/{account_id}/orders",
                json=order_payload,
            )
            location = resp.headers.get("location", "")
            return location.rsplit("/", 1)[-1] if location else ""
        except Exception as exc:  # noqa: BLE001
            logger.error("place_order failed: %s", map_http_error(exc))
            raise

    @with_backoff()
    def replace_order(self, account_id: str, order_id: str, order_payload: Dict[str, Any]) -> str:
        """Replace an existing order."""
        resp = self._request(
            "PUT",
            f"{self._base_url}/accounts/{account_id}/orders/{order_id}",
            json=order_payload,
        )
        location = resp.headers.get("location", "")
        return location.rsplit("/", 1)[-1] if location else order_id

    @with_backoff()
    def cancel_order(self, account_id: str, order_id: str) -> None:
        """Cancel a working order."""
        resp = self._request("DELETE", f"{self._base_url}/accounts/{account_id}/orders/{order_id}")

    @with_backoff()
    def get_orders(self, account_id: str) -> Dict[str, Any]:
        """Fetch orders for reconciliation."""
        resp = self._request(
            "GET",
            f"{self._base_url}/accounts/{account_id}/orders",
            params={"maxResults": 200},
        )
        return resp.json()

    @with_backoff()
    def get_user_preference(self) -> Dict[str, Any]:
        """Fetch userPreference to obtain streamerInfo."""
        resp = self._request("GET", f"{self._base_url}/userPreference")
        return resp.json()

    @with_backoff()
    def fetch_price_history(
        self, symbol: str, start_ms: Optional[int], end_ms: Optional[int], freq: str
    ) -> Dict[str, Any]:
        """Retrieve historical candles used for AE inputs."""
        params: Dict[str, Any] = {"symbol": symbol}
        params.update(self._freq_params(freq))
        if start_ms is not None:
            params["startDate"] = start_ms
        if end_ms is not None:
            params["endDate"] = end_ms
        resp = self._request("GET", f"{self._md_base_url}/pricehistory", params=params)
        return resp.json()

    def _freq_params(self, freq: str) -> Dict[str, Any]:
        if freq == "1m":
            return {"periodType": "day", "period": 1, "frequencyType": "minute", "frequency": 1}
        if freq == "5m":
            return {"periodType": "day", "period": 5, "frequencyType": "minute", "frequency": 5}
        if freq == "1h":
            return {"periodType": "month", "period": 1, "frequencyType": "minute", "frequency": 60}
        if freq == "4h":
            return {"periodType": "month", "period": 6, "frequencyType": "minute", "frequency": 240}
        if freq == "1d":
            return {"periodType": "year", "period": 1, "frequencyType": "daily", "frequency": 1}
        raise ValueError(f"Unsupported freq {freq}")

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        resp = self._client.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code == 401 and hasattr(self._auth_token_provider, "refresh"):
            try:
                self._auth_token_provider.refresh()  # type: ignore[attr-defined]
                resp = self._client.request(method, url, headers=self._headers(), **kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.error("Token refresh failed: %s", exc)
                raise
        resp.raise_for_status()
        return resp
