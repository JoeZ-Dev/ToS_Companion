from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional, List
import threading

import base64
import os
import httpx

TOKEN_PATH = Path.home() / ".tos_companion" / "tokens.json"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"


class TokenProvider:
    """Auth token management with refresh (on-demand)."""

    def __init__(
        self,
        refresh_callback: Optional[Callable[[dict], dict]] = None,
        token_path: Path = TOKEN_PATH,
        state_callback: Optional[Callable[[str], None]] = None,
    ):
        self._token_path = token_path
        self._refresh_callback = refresh_callback
        self._token_cache = self._load_tokens()
        self._lock = threading.Lock()
        self._refreshing = False
        self._refresh_event = threading.Event()
        self._refresh_event.set()
        self._refresh_listeners: List[Callable[[dict], None]] = []
        self._state_callback = state_callback

    def __call__(self) -> str:
        self._maybe_refresh()
        return self._token_cache.get("access_token", "")

    def set_access_token(self, token: str, expires_at: Optional[float] = None) -> None:
        self._token_cache["access_token"] = token
        if expires_at:
            self._token_cache["expires_at"] = expires_at
        self._save_tokens()
        self._notify_listeners()

    def refresh(self, current: Optional[dict] = None) -> dict:
        """Public refresh entry; delegates to refresh_callback if provided."""
        tokens = current or self._token_cache
        try:
            if self._refresh_callback:
                new_tokens = self._refresh_callback(tokens)
            else:
                new_tokens = self._refresh_tokens(tokens)
            if new_tokens:
                self._token_cache.update(new_tokens)
                self._save_tokens()
                self._notify_listeners()
            else:
                if self._state_callback:
                    self._state_callback("AUTH_REQUIRED")
            return new_tokens or {}
        except Exception:
            if self._state_callback:
                self._state_callback("AUTH_REQUIRED")
            raise

    def _maybe_refresh(self) -> None:
        expires_at = self._token_cache.get("expires_at")
        now = time.time()
        if expires_at and now >= expires_at - 60:
            self._refresh_singleflight()

    def _refresh_singleflight(self) -> None:
        with self._lock:
            if self._refreshing:
                # wait for in-flight refresh
                event = self._refresh_event
            else:
                self._refreshing = True
                self._refresh_event.clear()
                event = None
        if event:
            event.wait()
            return
        try:
            if self._refresh_callback:
                new_tokens = self._refresh_callback(self._token_cache)
                if new_tokens:
                    self._token_cache.update(new_tokens)
                    self._save_tokens()
                    self._notify_listeners()
            else:
                new_tokens = self._refresh_tokens(self._token_cache)
                if new_tokens:
                    self._token_cache.update(new_tokens)
                    self._save_tokens()
                    self._notify_listeners()
                else:
                    if self._state_callback:
                        self._state_callback("AUTH_REQUIRED")
        except Exception:
            if self._state_callback:
                self._state_callback("AUTH_REQUIRED")
            raise
        finally:
            with self._lock:
                self._refreshing = False
                self._refresh_event.set()

    def _load_tokens(self) -> dict:
        if self._token_path.exists():
            try:
                return json.loads(self._token_path.read_text())
            except Exception:
                return {}
        return {}

    def _save_tokens(self) -> None:
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._token_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self._token_cache))
        tmp_path.replace(self._token_path)

    def _refresh_tokens(self, tokens: dict) -> dict:
        client_id = os.environ.get("SCHWAB_CLIENT_ID")
        client_secret = os.environ.get("SCHWAB_CLIENT_SECRET")
        refresh_token = tokens.get("refresh_token")
        if not client_id or not client_secret or not refresh_token:
            return {}
        auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {auth}"}
        resp = httpx.post(TOKEN_URL, data=data, headers=headers, timeout=10.0)
        resp.raise_for_status()
        body = resp.json()
        access_token = body.get("access_token")
        expires_in = body.get("expires_in", 1800)
        refresh_token_new = body.get("refresh_token", refresh_token)
        expires_at = time.time() + expires_in - 60
        return {"access_token": access_token, "expires_at": expires_at, "refresh_token": refresh_token_new}

    def add_refresh_listener(self, listener: Callable[[dict], None]) -> None:
        self._refresh_listeners.append(listener)

    def _notify_listeners(self) -> None:
        for listener in self._refresh_listeners:
            try:
                listener(self._token_cache)
            except Exception:
                continue
