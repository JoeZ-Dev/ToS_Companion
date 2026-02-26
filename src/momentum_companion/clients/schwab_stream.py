from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
import random
from typing import Callable, Optional

import websocket
from websocket import WebSocketConnectionClosedException

from momentum_companion.clients.stream_mapping import LevelOneCache
from momentum_companion.data.contracts import QuoteEvent
from momentum_companion.journal.writer import JournalWriter
from momentum_companion.utils.logging import logging
from websocket import WebSocketConnectionClosedException
from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


class SchwabStreamClient:
    """WebSocket streaming client that emits canonical quote events (Appendix D, §13.1)."""

    def __init__(
        self,
        streamer_info: dict,
        on_quote: Callable[[QuoteEvent], None],
        token_provider: Optional[object] = None,
        journal: Optional[JournalWriter] = None,
        state_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._streamer_info = streamer_info
        self._on_quote = on_quote
        self._token_provider = token_provider
        self._cache = LevelOneCache()
        self._ws: Optional[websocket.WebSocketApp] = None
        self._connected: bool = False
        self._active_symbol: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._last_ts_ms: Optional[int] = None
        self._connection_state: str = "DISCONNECTED"
        self._journal = journal
        self._state_callback = state_callback
        self._conn_id = 0
        self._reconnecting = False
        self._reconnect_thread: Optional[threading.Thread] = None
        self._closing = False
        self._streamer_info_lock = threading.Lock()
        self._auth_source = "unknown"
        self._max_retries = 6
        self._rest_provider = getattr(token_provider, "rest_client", None)
        if hasattr(self._token_provider, "add_refresh_listener"):
            try:
                self._token_provider.add_refresh_listener(self._on_token_refreshed)  # type: ignore[attr-defined]
            except Exception:
                logger.warning("Failed to register token refresh listener")

    def connect(self) -> None:
        """Open WebSocket and authenticate."""
        self._emit_state("CONNECTING")
        url = self._streamer_info.get("streamerSocketUrl", "")
        if not url:
            raise ValueError("Missing streamerSocketUrl")
        # Preflight token check to avoid hammering with bad/missing creds
        probe_token = self._auth_token()
        if not probe_token:
            logger.error("Stream connect skipped: missing streaming token; AUTH_REQUIRED")
            self._emit_state("AUTH_REQUIRED")
            return
        self._closing = False
        self._conn_id += 1
        conn_id = self._conn_id
        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(target=self._ws.run_forever, daemon=True, kwargs={"sslopt": {"check_hostname": False}})
        self._thread.name = f"schwab-stream-{conn_id}"
        self._thread.start()

    def subscribe_level_one(self, symbol: str) -> None:
        """Subscribe to LEVELONE_EQUITIES for the active symbol."""
        self._active_symbol = symbol
        if not self._connected or not self._ws:
            return
        sub_msg = {
            "service": "LEVELONE_EQUITIES",
            "command": "SUBS",
            "requestid": "2",
            "SchwabClientCustomerId": self._streamer_info["schwabClientCustomerId"],
            "SchwabClientCorrelId": self._streamer_info["schwabClientCorrelId"],
            "parameters": {"keys": symbol, "fields": "0,1,2,3,4,5,8"},
        }
        self._ws.send(json.dumps(sub_msg))

    def unsubscribe(self, symbol: str) -> None:
        """Unsubscribe from the active symbol stream."""
        if not self._connected or not self._ws:
            return
        unsub_msg = {
            "service": "LEVELONE_EQUITIES",
            "command": "UNSUBS",
            "requestid": "3",
            "SchwabClientCustomerId": self._streamer_info["schwabClientCustomerId"],
            "SchwabClientCorrelId": self._streamer_info["schwabClientCorrelId"],
            "parameters": {"keys": symbol},
        }
        self._ws.send(json.dumps(unsub_msg))

    def disconnect(self) -> None:
        """Close the stream connection."""
        if self._ws:
            self._closing = True
            self._ws.close()
        self._connected = False
        self._emit_state("DISCONNECTED")

    def is_connected(self) -> bool:
        """Return connection state."""
        return self._connected

    def connection_state(self) -> str:
        """CONNECTED / RECONNECTING / DISCONNECTED."""
        return self._connection_state

    def is_fresh(self, now_ms: int) -> bool:
        """Quote freshness <=5s per specs §5.3."""
        if self._last_ts_ms is None:
            return False
        return (now_ms - self._last_ts_ms) <= 5_000

    def _auth_token(self) -> str:
        # Prefer streaming token from streamerInfo; fallback to OAuth token if absent.
        token = self._streamer_info.get("token") or self._streamer_info.get("access_token", "")
        if token:
            self._auth_source = "streamer_token"
            return token
        if self._token_provider:
            self._auth_source = "oauth_bearer"
            try:
                return self._token_provider()
            except Exception:
                return ""
        self._auth_source = "missing"
        return ""

    def _on_token_refreshed(self, tokens: dict) -> None:
        """Refresh listener: restart stream with new token."""
        try:
            self.disconnect()
            self.connect()
        except Exception as exc:  # noqa: BLE001
            logger.error("Stream restart on token refresh failed: %s", exc)

    # Internal callbacks
    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        if ws is not self._ws:
            return
        sock = getattr(ws, "sock", None)
        token = self._auth_token()
        logger.info("Stream login attempt using %s", self._auth_source)
        login_msg = {
            "service": "ADMIN",
            "command": "LOGIN",
            "requestid": "1",
            "SchwabClientCustomerId": self._streamer_info["schwabClientCustomerId"],
            "SchwabClientCorrelId": self._streamer_info["schwabClientCorrelId"],
            "parameters": {
                "Authorization": token,
                "SchwabClientChannel": self._streamer_info["schwabClientChannel"],
                "SchwabClientFunctionId": self._streamer_info["schwabClientFunctionId"],
            },
        }
        if not sock:
            logger.error("Stream login skipped: socket not connected")
            self._cleanup_socket(ws)
            self._emit_state("ERROR")
            self._attempt_reconnect()
            return
        try:
            ws.send(json.dumps(login_msg))
        except WebSocketConnectionClosedException:
            logger.error("Stream login failed: socket closed")
            self._cleanup_socket(ws)
            self._emit_state("ERROR")
            self._attempt_reconnect()

    def _on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        if ws is not self._ws:
            return
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Malformed JSON from stream")
            return
        messages = []
        if payload.get("service"):
            messages.append(payload)
        if isinstance(payload.get("data"), list):
            messages.extend(payload["data"])
        if isinstance(payload.get("response"), list):
            messages.extend(payload["response"])
        # Ignore heartbeats/notify entries
        for msg in messages:
            service = msg.get("service")
            command = msg.get("command")
            if service == "ADMIN":
                content = msg.get("content") or {}
                if isinstance(content, list) and content:
                    content = content[0]
                code = content.get("code", 0) if isinstance(content, dict) else 0
                if command == "LOGIN" and code == 0:
                    self._connected = True
                    self._emit_state("CONNECTED")
                    if self._active_symbol:
                        self.subscribe_level_one(self._active_symbol)
                elif command == "LOGIN" and code != 0:
                    logger.error("Stream LOGIN failed code=%s", code)
                    self._emit_state("LOGIN_FAILED")
                if command == "LOGOUT":
                    self._emit_state("DISCONNECTED")
                    self._attempt_reconnect()
            elif service == "LEVELONE_EQUITIES":
                if isinstance(msg.get("content"), dict):
                    # SUBS/UNSUBS responses carry dict content; ignore
                    continue
                try:
                    event = self._cache.process_message(msg)
                except ValueError as exc:
                    logger.warning("Stream message dropped: %s", exc)
                    continue
                if event:
                    self._last_ts_ms = event["ts_ms"]
                    self._on_quote(event)

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        if ws is not self._ws:
            return
        logger.error("Stream error: %s", error)
        self._cleanup_socket(ws)
        self._emit_state("ERROR")
        self._attempt_reconnect()

    def _on_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        if ws is not self._ws:
            return
        logger.warning("Stream closed code=%s msg=%s (auth=%s)", close_status_code, close_msg, self._auth_source)
        self._connected = False
        self._emit_state("DISCONNECTED")
        if not self._closing:
            self._cleanup_socket(ws)
            self._attempt_reconnect()

    def _attempt_reconnect(self) -> None:
        if self._reconnecting:
            return
        self._reconnecting = True
        self._emit_state("RECONNECTING")

        def _worker() -> None:
            attempts = 0
            backoffs = [1, 2, 4, 8, 16]
            while attempts < self._max_retries:
                delay = backoffs[min(attempts, len(backoffs) - 1)]
                time.sleep(delay + random.uniform(0, 0.25))
                attempts += 1
                refreshed = self._refresh_streamer_info()
                if not refreshed:
                    logger.error("Reconnect aborted: missing streamer token; AUTH_REQUIRED")
                    self._emit_state("AUTH_REQUIRED")
                    break
                try:
                    self.connect()
                    if self._active_symbol:
                        self.subscribe_level_one(self._active_symbol)
                    self._reconnecting = False
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.error("Reconnect attempt failed: %s", exc)
            self._reconnecting = False
            self._emit_state("DOWN")
            if self._journal:
                try:
                    self._journal.append_event(
                        {
                            "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "symbol": self._active_symbol or "",
                            "event_type": "STREAM_DOWN",
                            "session_mode": "SEAMLESS",
                            "connection_state": "RECONNECTING",
                            "notes_json": "STREAM_DOWN",
                        }
                    )
                except Exception:
                    logger.error("Failed to journal STREAM_DOWN")
            self._emit_state("STREAM_DOWN")

        self._reconnect_thread = threading.Thread(target=_worker, daemon=True, name="schwab-stream-reconnect")
        self._reconnect_thread.start()

    def _refresh_streamer_info(self) -> bool:
        """Attempt to reload streamer info/token; return True if a streaming token is present."""
        # Try via TokenProvider if it exposes rest_client
        rest = getattr(self._token_provider, "rest_client", None)
        if rest:
            try:
                prefs = rest.get_user_preference()
                info = prefs[0]["streamerInfo"][0] if isinstance(prefs, list) else prefs["streamerInfo"][0]
                if "token" not in info and "streamerInfo" in info:
                    info["token"] = info["streamerInfo"].get("token")  # type: ignore[index]
                if info.get("token"):
                    with self._streamer_info_lock:
                        self._streamer_info = info
                    return True
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to refresh streamer info: %s", exc)
        # No token available
        return bool(self._streamer_info.get("token"))

    def _cleanup_socket(self, ws: websocket.WebSocketApp) -> None:
        if ws is self._ws:
            try:
                ws.close()
            except Exception:
                pass
            self._ws = None
            self._connected = False

    def _emit_state(self, state: str) -> None:
        self._connection_state = state
        if self._state_callback:
            try:
                self._state_callback(state)
            except Exception:
                logger.error("Failed to emit state callback: %s", state)
