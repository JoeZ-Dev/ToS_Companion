from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx


class MassiveFundamentalsClient:
    FLOAT_TTL_SEC = 24 * 60 * 60
    SHORT_INTEREST_TTL_SEC = 7 * 24 * 60 * 60
    SHORT_VOL_TTL_SEC = 5 * 60

    def __init__(self, api_key: str, cache_dir: Path, logger) -> None:
        self._api_key = api_key
        self._cache_dir = cache_dir
        self._cache_path = cache_dir / "massive_cache.json"
        self._logger = logger
        self._session = httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0))
        self._cache: dict[str, Any] = {}
        try:
            if self._cache_path.exists():
                self._cache = json.loads(self._cache_path.read_text())
        except Exception:
            self._cache = {}

    def _cache_get(self, key: str, ttl_sec: int) -> dict | None:
        now = time.time()
        entry = self._cache.get(key)
        if not isinstance(entry, dict):
            return None
        ts = entry.get("ts")
        if ts is None or now - float(ts) > ttl_sec:
            return None
        return entry.get("data")

    def _cache_set(self, key: str, data: dict) -> None:
        self._cache[key] = {"ts": time.time(), "data": data}
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(self._cache))
        except Exception:
            pass

    def _status_from_resp(self, resp: httpx.Response, results: list | None) -> str:
        if resp.status_code in (401, 403):
            return "UNAUTHORIZED"
        if resp.status_code == 429:
            return "RATE_LIMIT"
        if resp.is_error or not results:
            return "FAILURE"
        return "OK"

    def fetch_float(self, symbol: str) -> dict:
        cache_key = f"float:{symbol}"
        cached = self._cache_get(cache_key, self.FLOAT_TTL_SEC)
        if cached:
            return cached
        endpoints = ["/stocks/v1/float", "/stocks/v2/float", "/stocks/v3/float"]
        for ep in endpoints:
            url = f"https://api.massive.com{ep}"
            params = {
                "ticker": symbol,
                "limit": 1,
                "sort": "effective_date.desc",
                "apiKey": self._api_key,
            }
            try:
                resp = self._session.get(url, params=params)
                results = resp.json().get("results") if resp.content else None
                status = self._status_from_resp(resp, results if isinstance(results, list) else None)
                self._logger.info(
                    "Massive float fetch status=%s symbol=%s ep=%s latency_ms=%s",
                    status,
                    symbol,
                    ep,
                    int(resp.elapsed.total_seconds() * 1000),
                )
                if status != "OK":
                    return {"status": status, "value": None, "as_of": None}
                rec = results[0] if results else {}
                data = {"status": "OK", "value": rec.get("free_float"), "as_of": rec.get("effective_date")}
                self._cache_set(cache_key, data)
                return data
            except (httpx.TimeoutException, httpx.RequestError):
                # retry only on next ep
                continue
            except Exception:
                self._logger.debug("Massive float fetch failed ep=%s", ep, exc_info=True)
                return {"status": "FAILURE", "value": None, "as_of": None}
        return {"status": "FAILURE", "value": None, "as_of": None}

    def fetch_short_interest(self, symbol: str) -> dict:
        cache_key = f"short_interest:{symbol}"
        cached = self._cache_get(cache_key, self.SHORT_INTEREST_TTL_SEC)
        if cached:
            return cached
        url = "https://api.massive.com/stocks/v1/short-interest"
        params = {
            "ticker": symbol,
            "limit": 1,
            "sort": "settlement_date.desc",
            "apiKey": self._api_key,
        }
        try:
            resp = self._session.get(url, params=params)
            results = resp.json().get("results") if resp.content else None
            status = self._status_from_resp(resp, results if isinstance(results, list) else None)
            self._logger.info(
                "Massive short_interest fetch status=%s symbol=%s latency_ms=%s",
                status,
                symbol,
                int(resp.elapsed.total_seconds() * 1000),
            )
            if status != "OK":
                return {"status": status, "value": None, "as_of": None}
            rec = results[0] if results else {}
            data = {"status": "OK", "value": rec.get("short_interest"), "as_of": rec.get("settlement_date")}
            self._cache_set(cache_key, data)
            return data
        except (httpx.TimeoutException, httpx.RequestError):
            return {"status": "FAILURE", "value": None, "as_of": None}
        except Exception:
            self._logger.debug("Massive short_interest fetch failed", exc_info=True)
            return {"status": "FAILURE", "value": None, "as_of": None}

    def fetch_short_volume_pct(self, symbol: str, today: str | None) -> dict:
        cache_key = f"short_vol:{symbol}"
        cached = self._cache_get(cache_key, self.SHORT_VOL_TTL_SEC)
        if cached:
            return cached
        attempts = []
        if today:
            attempts.append(
                ("today", {"date": today, "limit": 1, "apiKey": self._api_key, "ticker": symbol})
            )
        attempts.append(
            (
                "latest",
                {"limit": 1, "sort": "date.desc", "apiKey": self._api_key, "ticker": symbol},
            )
        )
        url = "https://api.massive.com/stocks/v1/short-volume"
        for label, params in attempts:
            try:
                resp = self._session.get(url, params=params)
                results = resp.json().get("results") if resp.content else None
                status = self._status_from_resp(resp, results if isinstance(results, list) else None)
                self._logger.info(
                    "Massive short_volume fetch status=%s symbol=%s attempt=%s latency_ms=%s",
                    status,
                    symbol,
                    label,
                    int(resp.elapsed.total_seconds() * 1000),
                )
                if status != "OK":
                    if label == "latest" or status in {"UNAUTHORIZED", "RATE_LIMIT"}:
                        return {"status": status, "value": None, "as_of": None}
                    continue
                rec = results[0] if results else {}
                data = {
                    "status": "OK",
                    "value": rec.get("short_volume_ratio"),
                    "as_of": rec.get("date"),
                    "used_fallback": label != "today",
                }
                self._cache_set(cache_key, data)
                return data
            except (httpx.TimeoutException, httpx.RequestError):
                continue
            except Exception:
                self._logger.debug("Massive short_volume fetch failed (%s)", label, exc_info=True)
                return {"status": "FAILURE", "value": None, "as_of": None}
        return {"status": "FAILURE", "value": None, "as_of": None}

    def test_key(self, symbol: str = "SPY") -> str:
        """Cheap probe using short-interest endpoint."""
        url = "https://api.massive.com/stocks/v1/short-interest"
        params = {"ticker": symbol, "limit": 1, "apiKey": self._api_key}
        try:
            resp = self._session.get(url, params=params)
            results = resp.json().get("results") if resp.content else None
            status = self._status_from_resp(resp, results if isinstance(results, list) else None)
            return status
        except (httpx.TimeoutException, httpx.RequestError):
            return "FAILURE"
        except Exception:
            return "FAILURE"
