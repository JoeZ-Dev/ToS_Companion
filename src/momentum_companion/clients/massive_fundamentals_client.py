from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import logging


class MassiveFundamentalsClient:
    BASE_URL = "https://api.massive.com"
    BASE_URL_POLYGON = "https://api.polygon.io"
    MASSIVE_FLOAT_PATH = "/stocks/v1/float"
    FLOAT_TTL_SEC = 24 * 60 * 60
    SHORT_INTEREST_TTL_SEC = 7 * 24 * 60 * 60
    SHORT_VOL_TTL_SEC = 5 * 60

    def __init__(self, api_key: str, cache_dir: Path, logger) -> None:
        self._api_key = api_key
        self._cache_dir = cache_dir
        self._cache_path = cache_dir / "massive_cache.json"
        self._logger = logger
        logging.getLogger("httpx").setLevel(logging.WARNING)
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
        code = resp.status_code
        if code in (401, 403):
            return "UNAUTHORIZED"
        if code == 429:
            return "RATE_LIMIT"
        if code == 404:
            return "FAILURE"
        if code < 200 or code >= 300:
            return "FAILURE"
        if not results:
            return "FAILURE"
        return "OK"

    @staticmethod
    def _has_keys(rec: dict | None, keys: tuple[str, ...]) -> bool:
        if not isinstance(rec, dict):
            return False
        return all(k in rec for k in keys)

    def _maybe_json(self, resp: httpx.Response) -> dict | None:
        ctype = resp.headers.get("content-type", "").lower()
        if "json" not in ctype:
            return None
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError):
            return None

    def _log_debug_failure(self, ep: str, resp: httpx.Response) -> None:
        try:
            snippet = resp.text[:120] if resp.text else ""
        except Exception:
            snippet = ""
        self._logger.debug(
            "Massive float fetch failed ep=%s status=%s ctype=%s body=%s",
            ep,
            resp.status_code,
            resp.headers.get("content-type"),
            snippet,
        )

    def fetch_float(self, symbol: str) -> dict:
        cache_key = f"float:{symbol}"
        cached = self._cache_get(cache_key, self.FLOAT_TTL_SEC)
        if cached:
            return cached
        params = {
            "ticker": symbol,
            "limit": 1,
            "sort": "effective_date.desc",
            "apiKey": self._api_key,
        }
        attempts = [
            ("massive", f"{self.BASE_URL}{self.MASSIVE_FLOAT_PATH}"),
            ("polygon", f"{self.BASE_URL_POLYGON}{self.MASSIVE_FLOAT_PATH}"),
        ]
        for label, url in attempts:
            try:
                resp = self._session.get(url, params=params)
                parsed = self._maybe_json(resp)
                results = parsed.get("results") if isinstance(parsed, dict) else None
                if not isinstance(results, list) or not results or not self._has_keys(results[0], ("free_float", "effective_date")):
                    if resp.status_code == 404:
                        self._logger.info(
                            "Massive float endpoint not found (404) attempt=%s status=%s ctype=%s body=%s",
                            label,
                            resp.status_code,
                            resp.headers.get("content-type"),
                            (resp.text[:120] if hasattr(resp, "text") else ""),
                        )
                        if label == "polygon":
                            return {"status": "FAILURE", "value": None, "as_of": None}
                        continue
                    self._log_debug_failure(self.MASSIVE_FLOAT_PATH, resp)
                    if label == "polygon":
                        return {"status": "FAILURE", "value": None, "as_of": None}
                    continue
                status = self._status_from_resp(resp, results)
                self._logger.info(
                    "Massive float fetch status=%s symbol=%s attempt=%s latency_ms=%s",
                    status,
                    symbol,
                    label,
                    int(resp.elapsed.total_seconds() * 1000),
                )
                if status != "OK":
                    if label == "polygon":
                        return {"status": status, "value": None, "as_of": None}
                    continue
                rec = results[0] if results else {}
                data = {"status": "OK", "value": rec.get("free_float"), "as_of": rec.get("effective_date")}
                self._cache_set(cache_key, data)
                return data
            except (httpx.TimeoutException, httpx.RequestError):
                if label == "polygon":
                    return {"status": "FAILURE", "value": None, "as_of": None}
                continue
            except Exception:
                self._logger.debug("Massive float fetch failed attempt=%s", label, exc_info=True)
                if label == "polygon":
                    return {"status": "FAILURE", "value": None, "as_of": None}
                continue
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
            parsed = self._maybe_json(resp)
            results = parsed.get("results") if isinstance(parsed, dict) else None
            if not isinstance(results, list) or not results or not self._has_keys(results[0], ("short_interest", "settlement_date")):
                return {"status": "FAILURE", "value": None, "as_of": None}
            status = self._status_from_resp(resp, results)
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
                parsed = self._maybe_json(resp)
                results = parsed.get("results") if isinstance(parsed, dict) else None
                if not isinstance(results, list) or not results or not self._has_keys(results[0], ("short_volume_ratio", "date")):
                    if label == "latest":
                        status = self._status_from_resp(resp, results if isinstance(results, list) else None)
                        return {"status": status, "value": None, "as_of": None}
                    self._logger.info("Massive short_volume today empty; falling back to latest")
                    continue
                status = self._status_from_resp(resp, results)
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
