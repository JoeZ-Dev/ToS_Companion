from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Dict, Optional

import httpx
from platformdirs import user_config_dir

TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
DEFAULT_SCOPE = "readonly streamerapi trade"


def default_token_path() -> Path:
    env_path = os.environ.get("AUTH_HELPER_TOKEN_PATH")
    if env_path:
        return Path(env_path)
    return Path(user_config_dir("MomentumTradingCompanion")) / "tokens.json"


def load_tokens(path: Path) -> Optional[Dict[str, str]]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
    return None


def save_tokens(path: Path, tokens: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tokens, indent=2))
    tmp.replace(path)


def _basic_auth() -> str:
    client_id = os.environ.get("SCHWAB_CLIENT_ID")
    client_secret = os.environ.get("SCHWAB_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("SCHWAB_CLIENT_ID/SECRET required on homelab")
    creds = f"{client_id}:{client_secret}".encode()
    return base64.b64encode(creds).decode()


def refresh_tokens(current: Dict[str, str]) -> Dict[str, str]:
    refresh_token = current.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("No refresh_token present; run interactive bootstrap.")
    scope = DEFAULT_SCOPE
    headers = {
        "Authorization": f"Basic {_basic_auth()}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token, "scope": scope}
    resp = httpx.post(TOKEN_URL, data=data, headers=headers, timeout=15.0)
    resp.raise_for_status()
    body = resp.json()
    expires_in = body.get("expires_in", 1800)
    expires_at = int(time.time()) + int(expires_in) - 60
    return {
        "access_token": body.get("access_token"),
        "refresh_token": body.get("refresh_token", refresh_token),
        "expires_at": expires_at,
    }


def ensure_access_token(path: Path | None = None) -> Dict[str, str]:
    path = path or default_token_path()
    tokens = load_tokens(path) or {}
    now = int(time.time())
    if tokens.get("access_token") and tokens.get("expires_at", 0) > now + 60:
        return {"access_token": tokens["access_token"], "expires_at": tokens["expires_at"], "source": "homelab"}
    if tokens.get("refresh_token"):
        new_tokens = refresh_tokens(tokens)
        save_tokens(path, new_tokens)
        new_tokens["source"] = "homelab"
        return new_tokens
    raise RuntimeError("No refresh_token; run tools/auth_helper/bootstrap.py to perform OAuth.")
