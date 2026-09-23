#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ToS_Companion browser-service readiness.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8787",
        help="Base URL for the ToS_Companion service.",
    )
    args = parser.parse_args()

    url = args.base_url.rstrip("/") + "/api/readiness"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"ERROR: readiness request failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2, sort_keys=True))

    if not payload.get("ok"):
        return 3
    if not payload.get("companion_auth_helper_configured"):
        print("ERROR: companion_auth helper URL is not configured.", file=sys.stderr)
        return 4
    if not payload.get("companion_auth_authorized"):
        print("ERROR: companion_auth is not currently authorized.", file=sys.stderr)
        return 5

    print("READY: ToS_Companion browser backend and companion_auth are available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
