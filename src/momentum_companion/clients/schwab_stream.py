from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
import random
from typing import Callable, Optional
import os

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
        on_chart_bar: Optional[Callable[[dict], None]] = None,
        token_provider: Optional[object] = None,
        journal: Optional[JournalWriter] = None,
        state_callback: Optional[Callable[[str], None]] = None,
        raw_payload_callback: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._streamer_info = streamer_info
        self._on_quote = on_quote
        self._on_chart_bar = on_chart_bar
        self._token_provider = token_provider
        self._cache = LevelOneCache()
        self._ws: Optional[websocket.WebSocketApp] = None
        self._connected: bool = False
        self._active_symbol: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._last_ts_ms: Optional[int] = None
        self._last_level_one_monotonic: Optional[float] = None
        self._connected_since_monotonic: Optional[float] = None
        self._connection_state: str = "DISCONNECTED"
        self._journal = journal
        self._state_callback = state_callback
        self._raw_payload_callback = raw_payload_callback
        self._level_one_symbols: set[str] = set()
        self._conn_id = 0
        self._connecting = False
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
        self._chart_enabled = os.environ.get("ENABLE_CHART_STREAM", "1") != "0"
        self._chart_logged_keys = False
        self._qos_express_enabled = os.environ.get("ENABLE_STREAM_QOS_EXPRESS", "1") != "0"
        self._last_l1_message_monotonic: Optional[float] = None
        self._telemetry_window_started = time.monotonic()
        self._telemetry_l1_count = 0
        self._telemetry_intervals_ms: list[float] = []
        self._telemetry_server_lag_ms: list[float] = []
        self._telemetry_callback_ms: list[float] = []
        self._symbol_last_receive_monotonic: dict[str, float] = {}
        self._symbol_intervals_ms: dict[str, list[float]] = {}
        self._symbol_message_counts: dict[str, int] = {}

    def connect(self) -> None:
        """Open WebSocket and authenticate."""
        self._emit_state("CONNECTING")
        url = self._streamer_info.get("streamerSocketUrl", "")
        if not url:
            raise ValueError("Missing streamerSocketUrl")
        # Preflight token check to avoid hammering with bad/missing creds
        self._connecting = True
        try:
            probe_token = self._peek_token()
            if not probe_token and hasattr(self._token_provider, "refresh"):
                try:
                    self._token_provider.refresh()
                except Exception:
                    logger.warning("Stream connect token refresh failed", exc_info=True)
                probe_token = self._peek_token()
            if not probe_token:
                logger.error("Stream connect skipped: missing OAuth access token; AUTH_REQUIRED")
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
        finally:
            self._connecting = False

    def subscribe_level_one(self, symbol: str) -> None:
        """Replace LEVELONE_EQUITIES subscription with one active symbol."""
        self._active_symbol = symbol
        self.subscribe_level_one_symbols([symbol])

    def subscribe_level_one_symbols(self, symbols: list[str]) -> None:
        """Replace LEVELONE_EQUITIES subscription with the provided symbols."""
        normalized = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
        self._level_one_symbols = normalized
        if not self._connected or not self._ws or not normalized:
            return
        sub_msg = {
            "service": "LEVELONE_EQUITIES",
            "command": "SUBS",
            "requestid": "2",
            "SchwabClientCustomerId": self._streamer_info["schwabClientCustomerId"],
            "SchwabClientCorrelId": self._streamer_info["schwabClientCorrelId"],
            "parameters": {
                "keys": ",".join(sorted(normalized)),
                "fields": "0,1,2,3,4,5,8,9,10,11,12,13,14,15,32,42,43,46,47,48,49",
            },
        }
        self._ws.send(json.dumps(sub_msg))

    def _send_express_qos(self) -> bool:
        """Request the fastest documented streamer QoS level (0 = 500 ms)."""
        if not self._connected or not self._ws or not self._qos_express_enabled:
            return False
        qos_msg = {
            "service": "ADMIN",
            "command": "QOS",
            "requestid": "6",
            "SchwabClientCustomerId": self._streamer_info["schwabClientCustomerId"],
            "SchwabClientCorrelId": self._streamer_info["schwabClientCorrelId"],
            "parameters": {"qoslevel": "0"},
        }
        try:
            self._ws.send(json.dumps(qos_msg))
            logger.info("Requested Schwab stream QOS=0 (Express/500ms)")
            return True
        except Exception:
            logger.warning("Failed to send Schwab stream QOS request", exc_info=True)
            return False

    def unsubscribe(self, symbol: str) -> None:
        """Unsubscribe one symbol and keep reconnect state consistent."""
        normalized = str(symbol).strip().upper()
        self._level_one_symbols.discard(normalized)
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
        if self._chart_enabled:
            self.unsubscribe_chart(symbol)

    def subscribe_chart(self, symbol: str) -> None:
        """Subscribe to CHART_EQUITY for 10s bars."""
        if not self._connected or not self._ws:
            return
        sub_msg = {
            "service": "CHART_EQUITY",
            "command": "SUBS",
            "requestid": "4",
            "SchwabClientCustomerId": self._streamer_info["schwabClientCustomerId"],
            "SchwabClientCorrelId": self._streamer_info["schwabClientCorrelId"],
            "parameters": {
                "keys": symbol,
                "fields": "0,1,2,3,4,5,6,7,8",
                "frequency": "10",
            },
        }
        logger.info("Chart stream enabled; subscribing CHART_EQUITY for %s", symbol)
        self._ws.send(json.dumps(sub_msg))

    def unsubscribe_chart(self, symbol: str) -> None:
        """Unsubscribe from CHART_EQUITY."""
        if not self._connected or not self._ws:
            return
        unsub_msg = {
            "service": "CHART_EQUITY",
            "command": "UNSUBS",
            "requestid": "5",
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

    def seconds_since_last_level_one(self) -> Optional[float]:
        """Return local receive age for L1 traffic while connected."""
        if not self._connected:
            return None
        reference = self._last_level_one_monotonic
        if reference is None:
            reference = self._connected_since_monotonic
        if reference is None:
            return None
        return max(0.0, time.monotonic() - reference)

    def refresh_level_one_subscription(self) -> bool:
        """Re-send the full desired L1 subscription set on the current socket."""
        if not self._connected or not self._ws or not self._level_one_symbols:
            return False
        logger.warning(
            "Refreshing stale LEVELONE_EQUITIES subscription for %s",
            ",".join(sorted(self._level_one_symbols)),
        )
        self.subscribe_level_one_symbols(sorted(self._level_one_symbols))
        return True

    def force_reconnect(self, reason: str) -> None:
        """Close the current socket and start the normal reconnect path."""
        logger.warning("Forcing Schwab stream reconnect: %s", reason)
        ws = self._ws
        if ws is not None:
            self._cleanup_socket(ws)
        else:
            self._connected = False
        self._connected_since_monotonic = None
        self._last_level_one_monotonic = None
        self._attempt_reconnect()

    def _auth_token(self) -> str:
        # Prefer streaming token from streamerInfo; fallback to OAuth token if absent.
        # Safe fallback: prefer streamer token if ever provided, but accept OAuth bearer for LOGIN.
        token = self._peek_token()
        if token:
            self._auth_source = "streamer_token"
            return token
        if self._token_provider:
            try:
                fallback = self._token_provider()
                if fallback:
                    self._auth_source = "oauth_bearer"
                    return fallback
            except Exception:
                pass
        self._auth_source = "missing"
        return ""

    def _on_token_refreshed(self, tokens: dict) -> None:
        """Refresh listener: restart stream with new token."""
        if self._connecting:
            logger.debug("Stream token refresh ignored (connect in progress)")
            return
        if not self._connected and self._connection_state != "CONNECTED":
            return
        try:
            self.disconnect()
            self.connect()
        except Exception as exc:  # noqa: BLE001
            logger.error("Stream restart on token refresh failed: %s", exc)

    def _peek_token(self) -> str:
        if self._token_provider and hasattr(self._token_provider, "peek_access_token"):
            return self._token_provider.peek_access_token()  # type: ignore[attr-defined]
        return self._streamer_info.get("token") or self._streamer_info.get("access_token", "") or ""

    # Internal callbacks
    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        if ws is not self._ws:
            return
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
        try:
            ws.send(json.dumps(login_msg))
        except WebSocketConnectionClosedException:
            logger.error("Stream login failed: socket closed")
            self._cleanup_socket(ws)
            self._emit_state("ERROR")
            self._attempt_reconnect()
        except Exception:
            logger.error("Stream login send failed unexpectedly", exc_info=True)
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
        if self._raw_payload_callback is not None:
            try:
                self._raw_payload_callback(payload)
            except Exception:
                logger.warning("Raw stream payload callback failed", exc_info=True)
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
                    self._connected_since_monotonic = time.monotonic()
                    self._last_level_one_monotonic = None
                    self._emit_state("CONNECTED")
                    self._send_express_qos()
                    if self._level_one_symbols:
                        self.subscribe_level_one_symbols(sorted(self._level_one_symbols))
                    elif self._active_symbol:
                        self.subscribe_level_one(self._active_symbol)
                    if self._active_symbol and self._chart_enabled:
                        self.subscribe_chart(self._active_symbol)
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
                receive_monotonic = time.monotonic()
                receive_wall_ms = int(time.time() * 1000)
                callback_started = time.perf_counter()
                self._last_level_one_monotonic = receive_monotonic
                if self._last_l1_message_monotonic is not None:
                    self._telemetry_intervals_ms.append(
                        (receive_monotonic - self._last_l1_message_monotonic) * 1000.0
                    )
                self._last_l1_message_monotonic = receive_monotonic
                server_ts = msg.get("timestamp")
                if server_ts is not None:
                    try:
                        self._telemetry_server_lag_ms.append(float(receive_wall_ms - int(server_ts)))
                    except (TypeError, ValueError):
                        pass
                self._telemetry_l1_count += 1
                try:
                    events = self._cache.process_messages(msg)
                except ValueError as exc:
                    logger.warning("Stream message dropped: %s", exc)
                    continue
                for event in events:
                    symbol = str(event.get("symbol") or "").strip().upper()
                    if symbol:
                        previous_symbol_receive = self._symbol_last_receive_monotonic.get(symbol)
                        if previous_symbol_receive is not None:
                            self._symbol_intervals_ms.setdefault(symbol, []).append(
                                (receive_monotonic - previous_symbol_receive) * 1000.0
                            )
                        self._symbol_last_receive_monotonic[symbol] = receive_monotonic
                        self._symbol_message_counts[symbol] = self._symbol_message_counts.get(symbol, 0) + 1
                    self._last_ts_ms = event["ts_ms"]
                    self._on_quote(event)
                self._telemetry_callback_ms.append((time.perf_counter() - callback_started) * 1000.0)
                self._maybe_log_stream_telemetry(receive_monotonic)
            elif service == "CHART_EQUITY":
                content = msg.get("content") or []
                if isinstance(content, list) and self._on_chart_bar:
                    if content and not self._chart_logged_keys:
                        try:
                            keys = list(content[0].keys())
                            logger.debug("CHART_EQUITY first payload keys=%s", keys)
                        except Exception:
                            pass
                        self._chart_logged_keys = True
                    for bar in content:
                        try:
                            symbol = bar.get("key")
                            ts_ms = bar.get("7") or msg.get("timestamp")
                            if symbol is None or ts_ms is None:
                                continue
                            # Field mapping: 2=open,3=high,4=low,5=close,6=volume
                            mapped = {
                                "symbol": symbol,
                                "ts_ms": int(ts_ms),
                                "open": float(bar.get("2")) if bar.get("2") is not None else None,
                                "high": float(bar.get("3")) if bar.get("3") is not None else None,
                                "low": float(bar.get("4")) if bar.get("4") is not None else None,
                                "close": float(bar.get("5")) if bar.get("5") is not None else None,
                                "volume": float(bar.get("6")) if bar.get("6") is not None else None,
                            }
                            if None in (mapped["open"], mapped["high"], mapped["low"], mapped["close"], mapped["volume"]):
                                continue
                            self._on_chart_bar(mapped)
                        except Exception:
                            logger.debug("Failed to process CHART_EQUITY bar", exc_info=True)

    def _maybe_log_stream_telemetry(self, now_monotonic: float) -> None:
        if now_monotonic - self._telemetry_window_started < 5.0:
            return
        intervals = self._telemetry_intervals_ms
        lags = self._telemetry_server_lag_ms
        callbacks = self._telemetry_callback_ms
        logger.info(
            "STREAM_TELEMETRY window=5s l1_messages=%d interval_avg_ms=%s interval_max_ms=%s "
            "server_lag_avg_ms=%s server_lag_max_ms=%s callback_avg_ms=%s callback_max_ms=%s",
            self._telemetry_l1_count,
            f"{sum(intervals) / len(intervals):.1f}" if intervals else "n/a",
            f"{max(intervals):.1f}" if intervals else "n/a",
            f"{sum(lags) / len(lags):.1f}" if lags else "n/a",
            f"{max(lags):.1f}" if lags else "n/a",
            f"{sum(callbacks) / len(callbacks):.1f}" if callbacks else "n/a",
            f"{max(callbacks):.1f}" if callbacks else "n/a",
        )
        for symbol in sorted(self._symbol_message_counts):
            symbol_intervals = self._symbol_intervals_ms.get(symbol) or []
            logger.info(
                "STREAM_SYMBOL_TELEMETRY symbol=%s messages=%d interval_avg_ms=%s interval_max_ms=%s",
                symbol,
                self._symbol_message_counts[symbol],
                f"{sum(symbol_intervals) / len(symbol_intervals):.1f}" if symbol_intervals else "n/a",
                f"{max(symbol_intervals):.1f}" if symbol_intervals else "n/a",
            )
        self._telemetry_window_started = now_monotonic
        self._telemetry_l1_count = 0
        self._telemetry_intervals_ms.clear()
        self._telemetry_server_lag_ms.clear()
        self._telemetry_callback_ms.clear()
        self._symbol_intervals_ms.clear()
        self._symbol_message_counts.clear()

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        if ws is not self._ws:
            return
        try:
            logger.error("Stream error: %s", error)
            self._cleanup_socket(ws)
            self._emit_state("ERROR")
            self._attempt_reconnect()
        except Exception:
            logger.warning("Stream on_error handling failed", exc_info=True)

    def _on_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        if ws is not self._ws:
            return
        try:
            logger.warning("Stream closed code=%s msg=%s (auth=%s)", close_status_code, close_msg, self._auth_source)
            self._connected = False
            self._emit_state("DISCONNECTED")
            if not self._closing:
                self._cleanup_socket(ws)
                self._attempt_reconnect()
        except Exception:
            logger.warning("Stream on_close handling failed", exc_info=True)

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
                if not self._auth_token():
                    logger.error("Reconnect aborted: missing OAuth access token; AUTH_REQUIRED")
                    self._emit_state("AUTH_REQUIRED")
                    break
                try:
                    self.connect()
                    if self._level_one_symbols:
                        self.subscribe_level_one_symbols(sorted(self._level_one_symbols))
                    elif self._active_symbol:
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
        """Attempt to reload streamer info; return True if identity fields are present."""
        # Try via TokenProvider if it exposes rest_client
        rest = getattr(self._token_provider, "rest_client", None)
        if rest:
            try:
                prefs = rest.get_user_preference()
                info = prefs[0]["streamerInfo"][0] if isinstance(prefs, list) else prefs["streamerInfo"][0]
                required_keys = {"streamerSocketUrl", "schwabClientCustomerId", "schwabClientCorrelId", "schwabClientChannel", "schwabClientFunctionId"}
                if required_keys.issubset(info):
                    with self._streamer_info_lock:
                        self._streamer_info = info
                    return True
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to refresh streamer info: %s", exc)
        # No update; fall back to existing streamer_info if it has identity fields
        required_keys = {"streamerSocketUrl", "schwabClientCustomerId", "schwabClientCorrelId", "schwabClientChannel", "schwabClientFunctionId"}
        return required_keys.issubset(self._streamer_info)

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
