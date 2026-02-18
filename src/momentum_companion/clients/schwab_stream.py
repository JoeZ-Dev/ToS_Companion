from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import websocket

from momentum_companion.clients.stream_mapping import LevelOneCache
from momentum_companion.data.contracts import QuoteEvent
from momentum_companion.journal.writer import JournalWriter
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
        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(target=self._ws.run_forever, daemon=True)
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
        if self._token_provider:
            return self._token_provider()
        return self._streamer_info.get("access_token", "")

    def _on_token_refreshed(self, tokens: dict) -> None:
        """Refresh listener: restart stream with new token."""
        try:
            self.disconnect()
            self.connect()
        except Exception as exc:  # noqa: BLE001
            logger.error("Stream restart on token refresh failed: %s", exc)

    # Internal callbacks
    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        login_msg = {
            "service": "ADMIN",
            "command": "LOGIN",
            "requestid": "1",
            "SchwabClientCustomerId": self._streamer_info["schwabClientCustomerId"],
            "SchwabClientCorrelId": self._streamer_info["schwabClientCorrelId"],
            "parameters": {
                "Authorization": self._auth_token(),
                "SchwabClientChannel": self._streamer_info["schwabClientChannel"],
                "SchwabClientFunctionId": self._streamer_info["schwabClientFunctionId"],
            },
        }
        ws.send(json.dumps(login_msg))

    def _on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Malformed JSON from stream")
            return
        if not isinstance(payload, dict):
            logger.warning("Non-dict payload dropped: %r", payload)
            return
        try:
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
                    content = msg.get("content")
                    if not isinstance(content, list):
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
        except Exception as exc:  # noqa: BLE001
            logger.error("Stream on_message failed: %s; payload=%r", exc, payload)

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        logger.error("Stream error: %s", error)
        self._emit_state("ERROR")

    def _on_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        self._connected = False
        self._emit_state("DISCONNECTED")
        self._attempt_reconnect()

    def _attempt_reconnect(self) -> None:
        self._emit_state("RECONNECTING")
        backoffs = [1, 2, 4, 8, 16, 32]
        for delay in backoffs:
            time.sleep(delay)
            try:
                self.connect()
                if self._active_symbol:
                    self.subscribe_level_one(self._active_symbol)
                return
            except Exception as exc:  # noqa: BLE001
                logger.error("Reconnect attempt failed: %s", exc)
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

    def _emit_state(self, state: str) -> None:
        self._connection_state = state
        if self._state_callback:
            try:
                self._state_callback(state)
            except Exception:
                logger.error("Failed to emit state callback: %s", state)
