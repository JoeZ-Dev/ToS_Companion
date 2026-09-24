from __future__ import annotations

import time
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
        tok_str = str(token or "").strip() if token is not None else ""
        if not tok_str:
            logger.warning("Missing auth token for Schwab REST request")
            return {}
        return {"Authorization": f"Bearer {tok_str}"}

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

        now_ms = int(time.time() * 1000)
        clamp_target = now_ms - 2000
        explicit_range = start_ms is not None or end_ms is not None

        params: Dict[str, Any] = {"symbol": symbol}
        params.update(self._freq_params(freq, include_period=not explicit_range))
        # Match the known-good Momentum Monitor request shape for explicit
        # intraday minute history: startDate/endDate + frequency only.
        # Schwab accepts periodType=day for period-based requests, but the
        # live-tested midnight backfill path intentionally omits periodType
        # (and period) when an explicit 1m range is supplied.
        if explicit_range and freq == "1m":
            params.pop("periodType", None)
            params.pop("period", None)

        if explicit_range:
            end = clamp_target if end_ms is None else min(int(end_ms), clamp_target)
            if start_ms is None:
                # Explicit end with no start is only used defensively; normal
                # callers provide both bounds.
                start = end - 60 * 60 * 1000
            else:
                start = int(start_ms)
            if start >= end:
                start = end - 60 * 1000
            params["startDate"] = start
            params["endDate"] = end
            logger.info(
                "pricehistory normalized freq=%s explicit_range=true start_ms=%s end_ms=%s now_ms=%s",
                freq, start, end, now_ms,
            )
        else:
            logger.info(
                "pricehistory normalized freq=%s explicit_range=false period_mode=true now_ms=%s",
                freq, now_ms,
            )

        params["needExtendedHoursData"] = "true"
        resp = self._request("GET", f"{self._md_base_url}/pricehistory", params=params)
        body = resp.json()
        candles = body.get("candles") or []
        first_ms = candles[0].get("datetime") if candles else None
        last_ms = candles[-1].get("datetime") if candles else None
        logger.info(
            "pricehistory result symbol=%s freq=%s candles=%d empty=%s first_ms=%s last_ms=%s",
            symbol,
            freq,
            len(candles),
            body.get("empty"),
            first_ms,
            last_ms,
        )
        return body

    def _freq_params(self, freq: str, *, include_period: bool = True) -> Dict[str, Any]:
        if freq == "1m":
            params = {"periodType": "day", "frequencyType": "minute", "frequency": 1}
            if include_period:
                params["period"] = 1
            return params
        if freq == "5m":
            params = {"periodType": "day", "frequencyType": "minute", "frequency": 5}
            if include_period:
                params["period"] = 5
            return params
        if freq == "1h":
            params = {"periodType": "day", "frequencyType": "minute", "frequency": 60}
            if include_period:
                params["period"] = 10
            return params
        if freq == "4h":
            # Schwab pricehistory does not expose 4h directly; use daily as a structural proxy.
            params = {"periodType": "year", "frequencyType": "daily", "frequency": 1}
            if include_period:
                params["period"] = 1
            return params
        if freq == "1d":
            params = {"periodType": "year", "frequencyType": "daily", "frequency": 1}
            if include_period:
                params["period"] = 1
            return params
        if freq == "day":
            params = {"periodType": "day", "frequencyType": "minute", "frequency": 1}
            if include_period:
                params["period"] = 1
            return params
        raise ValueError(f"Unsupported freq {freq}")

    @with_backoff()
    def fetch_quote_fundamental(self, symbol: str) -> Dict[str, Any]:
        """Fetch fundamental block (e.g., sharesOutstanding) for a single symbol."""
        params = {"fields": "fundamental"}
        resp = self._request("GET", f"{self._md_base_url}/{symbol}/quotes", params=params)
        return resp.json()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        resp = self._client.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code == 401 and hasattr(self._auth_token_provider, "refresh"):
            try:
                self._auth_token_provider.refresh()  # type: ignore[attr-defined]
                resp = self._client.request(method, url, headers=self._headers(), **kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.error("Token refresh failed: %s", exc)
                raise
        if resp.status_code == 400:
            try:
                params = kwargs.get("params")
                body = resp.text
                snippet = body[:2000] if body else body
                logger.error("Schwab 400 for %s %s params=%s body=%s", method, url, params, snippet)
            except Exception:
                logger.error("Schwab 400 for %s %s (failed to log body)", method, url)
        resp.raise_for_status()
        return resp
