"""
Redaction-safe REST probe for Schwab Market Data endpoints (MVP scope).

What it does:
- Calls only the endpoints we actually need for the MVP:
  * /marketdata/v1/quotes (multi-symbol)
  * /marketdata/v1/{symbol}/pricehistory
- Uses candidate parameters taken from in-repo Quick_Reference examples.
- Logs ONLY: endpoint path, query param keys used, HTTP status, and top-level
  response keys (never tokens or full payloads).

What it does NOT do:
- Store or print tokens.
- Persist payloads.

Usage:
  SCHWAB_ACCESS_TOKEN=<token> python rest_probe.py

Optional env overrides (dotenv supported):
  SYMBOLS=AAPL,MSFT
  PRICE_PERIOD_TYPE=day
  PRICE_PERIOD=10
  PRICE_FREQUENCY_TYPE=minute
  PRICE_FREQUENCY=1
"""

import json
import os
from typing import Any, Dict, Iterable, List, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.schwabapi.com/marketdata/v1"


def _env_list(key: str, default: str) -> List[str]:
    raw = os.environ.get(key, default)
    return [s.strip() for s in raw.split(",") if s.strip()]


def _top_level_keys(obj: Any) -> List[str]:
    if isinstance(obj, dict):
        return sorted(obj.keys())
    if isinstance(obj, list):
        return [f"<list_len={len(obj)}>"]
    return [f"<type={type(obj).__name__}>"]


def _probe(
    session: requests.Session, method: str, path: str, params: Dict[str, Any]
) -> Tuple[int, List[str], str]:
    url = f"{BASE_URL}{path}"
    try:
        resp = session.request(method, url, params=params, timeout=15)
        status = resp.status_code
        try:
            data = resp.json()
            keys = _top_level_keys(data)
            err = ""
        except Exception:
            data = None
            keys = []
            err = (resp.text or "").strip()[:200]
    except Exception as exc:
        status = -1
        keys = []
        err = str(exc)
    return status, keys, err


def main() -> None:
    access_token = os.environ.get("SCHWAB_ACCESS_TOKEN")
    if not access_token:
        raise SystemExit("SCHWAB_ACCESS_TOKEN is required (Bearer token).")

    symbols = _env_list("SYMBOLS", "AAPL")
    if not symbols:
        raise SystemExit("At least one symbol required in SYMBOLS.")

    price_params = {
        # Candidate params taken from docs/schwab/Quick_Reference.md
        "periodType": os.environ.get("PRICE_PERIOD_TYPE", "day"),
        "period": os.environ.get("PRICE_PERIOD", "10"),
        "frequencyType": os.environ.get("PRICE_FREQUENCY_TYPE", "minute"),
        "frequency": os.environ.get("PRICE_FREQUENCY", "1"),
    }

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {access_token}"})

    probes = [
        {
            "path": "/quotes",
            "method": "GET",
            "params": {"symbols": ",".join(symbols)},
            "label": "quotes_multi",
        },
        {
            "path": f"/{symbols[0]}/pricehistory",
            "method": "GET",
            "params": price_params,
            "label": "pricehistory_single",
        },
    ]

    results: List[Dict[str, Any]] = []
    for probe in probes:
        status, keys, err = _probe(
            session,
            method=probe["method"],
            path=probe["path"],
            params=probe["params"],
        )
        results.append(
            {
                "endpoint": probe["path"],
                "method": probe["method"],
                "query_keys": sorted(list(probe["params"].keys())),
                "status": status,
                "response_top_keys": keys,
                "error_excerpt": err,
            }
        )

    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
