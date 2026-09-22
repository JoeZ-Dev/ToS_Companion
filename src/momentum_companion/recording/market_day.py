from __future__ import annotations

import json
import threading
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Iterable, TextIO
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
CUTOFF_ET = dt_time(hour=15, minute=0)
RECORDED_SERVICES = frozenset({"TIMESALE_EQUITY", "LEVELONE_EQUITIES"})
SCHEMA_VERSION = 1


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = raw.strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


def reached_cutoff(now: datetime | None = None) -> bool:
    current = now or datetime.now(ET)
    current = current.replace(tzinfo=ET) if current.tzinfo is None else current.astimezone(ET)
    return current.time() >= CUTOFF_ET


def seconds_until_cutoff(now: datetime | None = None) -> float:
    current = now or datetime.now(ET)
    current = current.replace(tzinfo=ET) if current.tzinfo is None else current.astimezone(ET)
    cutoff = datetime.combine(current.date(), CUTOFF_ET, tzinfo=ET)
    return max(0.0, (cutoff - current).total_seconds())


def _extract_stream_messages(payload: dict) -> list[dict]:
    messages: list[dict] = []
    if payload.get("service"):
        messages.append(payload)
    data = payload.get("data")
    if isinstance(data, list):
        messages.extend(msg for msg in data if isinstance(msg, dict))
    return messages


def _entry_symbol(entry: dict) -> str:
    value = entry.get("key")
    if value is None:
        value = entry.get("0")
    return str(value or "").strip().upper()


def build_subscription_requests(
    streamer_info: dict, symbols: list[str], *, include_timesales: bool = False
) -> list[dict]:
    """Build supported L1 subscription and optional experimental T&S probe."""
    keys = ",".join(symbols)
    common = {
        "SchwabClientCustomerId": streamer_info["schwabClientCustomerId"],
        "SchwabClientCorrelId": streamer_info["schwabClientCorrelId"],
    }
    requests = [
        {
            "service": "LEVELONE_EQUITIES",
            "command": "SUBS",
            "requestid": "2",
            **common,
            "parameters": {
                "keys": keys,
                "fields": "0,1,2,3,4,5,8,9,10,11,12,13,14,15",
            },
        }
    ]
    if include_timesales:
        requests.append(
            {
                "service": "TIMESALE_EQUITY",
                "command": "SUBS",
                "requestid": "3",
                **common,
                "parameters": {"keys": keys, "fields": "0,1,2,3,4"},
            }
        )
    return requests


class MarketDayRecorder:
    """Persist raw replayable market events into one JSONL file per symbol."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        output_root: Path | None = None,
        started_at: datetime | None = None,
        services: Iterable[str] | None = None,
    ) -> None:
        self.symbols = normalize_symbols(symbols)
        if not self.symbols:
            raise ValueError("At least one symbol is required")
        self._symbol_set = set(self.symbols)
        selected_services = set(services or {"LEVELONE_EQUITIES"})
        unknown_services = selected_services - RECORDED_SERVICES
        if unknown_services:
            raise ValueError(f"Unsupported recording services: {sorted(unknown_services)}")
        if not selected_services:
            raise ValueError("At least one recording service is required")
        self.services = frozenset(selected_services)
        self.started_at = (started_at or datetime.now(ET)).astimezone(ET)
        root = output_root or (Path.home() / ".tos_companion" / "recordings")
        stamp = self.started_at.strftime("%Y-%m-%d_%H%M%S")
        label = "-".join(self.symbols)
        self.session_dir = root / f"{stamp}_{label}"
        self.session_dir.mkdir(parents=True, exist_ok=False)
        self._files: dict[str, TextIO] = {}
        self._counts: dict[str, dict[str, int]] = {
            sym: {service: 0 for service in sorted(self.services)} for sym in self.symbols
        }
        self._lock = threading.Lock()
        self._closed = False
        self._write_manifest(ended_at=None, stop_reason=None)

    def _file_for(self, symbol: str) -> TextIO:
        handle = self._files.get(symbol)
        if handle is None:
            handle = (self.session_dir / f"{symbol}.jsonl").open("a", encoding="utf-8")
            self._files[symbol] = handle
        return handle

    def record_payload(self, payload: dict, *, received_at: str | None = None) -> None:
        if self._closed:
            raise RuntimeError("Recorder is closed")
        received = received_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        with self._lock:
            for msg in _extract_stream_messages(payload):
                service = str(msg.get("service") or "")
                if service not in self.services:
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                stream_ts_ms = msg.get("timestamp")
                for entry in content:
                    if not isinstance(entry, dict):
                        continue
                    symbol = _entry_symbol(entry)
                    if symbol not in self._symbol_set:
                        continue
                    record = {
                        "schema_version": SCHEMA_VERSION,
                        "kind": "market_event",
                        "service": service,
                        "symbol": symbol,
                        "stream_ts_ms": stream_ts_ms,
                        "received_at": received,
                        "raw": entry,
                    }
                    handle = self._file_for(symbol)
                    handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                    handle.flush()
                    self._counts[symbol][service] += 1

    def close(self, *, stop_reason: str = "stopped") -> None:
        if self._closed:
            return
        with self._lock:
            for handle in self._files.values():
                handle.flush()
                handle.close()
            self._files.clear()
            self._closed = True
            self._write_manifest(
                ended_at=datetime.now(ET).isoformat(),
                stop_reason=stop_reason,
            )

    def _write_manifest(self, *, ended_at: str | None, stop_reason: str | None) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "kind": "market_day_recording",
            "symbols": self.symbols,
            "services": sorted(self.services),
            "started_at_et": self.started_at.isoformat(),
            "scheduled_cutoff_et": "15:00:00",
            "ended_at_et": ended_at,
            "stop_reason": stop_reason,
            "counts": self._counts,
        }
        (self.session_dir / "manifest.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )


class SchwabMarketDayRunner:
    """Connect, record several symbols, reconnect, and stop at 3 PM ET."""

    def __init__(self, recorder: MarketDayRecorder, *, probe_timesales: bool = False) -> None:
        self.recorder = recorder
        self.probe_timesales = probe_timesales
        self._stop = threading.Event()
        self._ws = None

    def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    @staticmethod
    def _streamer_info_from_preferences(prefs: object) -> dict:
        if isinstance(prefs, list):
            root = prefs[0] if prefs else None
        elif isinstance(prefs, dict):
            root = prefs
        else:
            root = None
        if not isinstance(root, dict):
            raise RuntimeError("Unexpected Schwab userPreference response")
        infos = root.get("streamerInfo")
        if not isinstance(infos, list) or not infos:
            raise RuntimeError("Schwab userPreference missing streamerInfo")
        return infos[0]

    def run(self) -> Path:
        if reached_cutoff():
            self.recorder.close(stop_reason="cutoff_already_reached")
            return self.recorder.session_dir

        import websocket

        from momentum_companion.clients.schwab_rest import SchwabRestClient
        from momentum_companion.clients.token_provider import TokenProvider

        token_provider = TokenProvider()
        rest = SchwabRestClient(
            base_url="https://api.schwabapi.com/trader/v1",
            auth_token_provider=token_provider,
        )

        threading.Thread(target=self._cutoff_watch, daemon=True).start()
        backoff = 1.0
        try:
            while not self._stop.is_set() and not reached_cutoff():
                try:
                    prefs = rest.get_user_preference()
                    streamer_info = self._streamer_info_from_preferences(prefs)
                    access_token = token_provider.peek_access_token() or token_provider()
                    if not access_token:
                        raise RuntimeError(
                            "No Schwab access token available from companion_auth/TokenProvider"
                        )
                    self._run_connection(websocket, streamer_info, access_token)
                    backoff = 1.0
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    if self._stop.is_set() or reached_cutoff():
                        break
                    print(f"Recorder disconnected: {exc}; reconnecting in {backoff:.0f}s")
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2.0, 15.0)
        finally:
            reason = "3pm_cutoff" if reached_cutoff() else "stopped"
            self.stop()
            self.recorder.close(stop_reason=reason)
        return self.recorder.session_dir

    def _cutoff_watch(self) -> None:
        delay = seconds_until_cutoff()
        if delay > 0:
            self._stop.wait(delay)
        if not self._stop.is_set():
            print("3:00 PM ET cutoff reached; stopping recorder.")
            self.stop()

    def _run_connection(self, websocket_module, streamer_info: dict, access_token: str) -> None:
        login_ok = threading.Event()

        def on_open(ws) -> None:
            ws.send(
                json.dumps(
                    {
                        "service": "ADMIN",
                        "command": "LOGIN",
                        "requestid": "1",
                        "SchwabClientCustomerId": streamer_info["schwabClientCustomerId"],
                        "SchwabClientCorrelId": streamer_info["schwabClientCorrelId"],
                        "parameters": {
                            "Authorization": access_token,
                            "SchwabClientChannel": streamer_info["schwabClientChannel"],
                            "SchwabClientFunctionId": streamer_info["schwabClientFunctionId"],
                        },
                    }
                )
            )

        def on_message(ws, message: str) -> None:
            payload = json.loads(message)
            responses = payload.get("response", []) if isinstance(payload, dict) else []
            for response in responses:
                if response.get("service") == "ADMIN" and response.get("command") == "LOGIN":
                    content = response.get("content") or []
                    first = content[0] if isinstance(content, list) and content else content
                    code = first.get("code") if isinstance(first, dict) else None
                    if code != 0:
                        raise RuntimeError(f"Schwab stream login failed code={code}")
                    login_ok.set()
                    ws.send(
                        json.dumps(
                            {
                                "service": "ADMIN",
                                "command": "QOS",
                                "requestid": "1a",
                                "SchwabClientCustomerId": streamer_info["schwabClientCustomerId"],
                                "SchwabClientCorrelId": streamer_info["schwabClientCorrelId"],
                                "parameters": {"qoslevel": 0},
                            }
                        )
                    )
                    for request in build_subscription_requests(
                        streamer_info,
                        self.recorder.symbols,
                        include_timesales=self.probe_timesales,
                    ):
                        ws.send(json.dumps(request))
            self.recorder.record_payload(payload)

        def on_error(_ws, error) -> None:
            print(f"Recorder websocket error: {error}")

        def on_close(_ws, code, message) -> None:
            if not self._stop.is_set() and not reached_cutoff():
                print(f"Recorder websocket closed code={code} message={message}")

        ws = websocket_module.WebSocketApp(
            streamer_info["streamerSocketUrl"],
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        self._ws = ws
        mode = "L1 + experimental T&S probe" if self.probe_timesales else "L1"
        print(
            f"Recording {', '.join(self.recorder.symbols)} ({mode}) until 3:00 PM ET -> "
            f"{self.recorder.session_dir}"
        )
        ws.run_forever(ping_interval=20, ping_timeout=10, sslopt={"check_hostname": False})
        self._ws = None
        if not login_ok.is_set() and not self._stop.is_set() and not reached_cutoff():
            raise RuntimeError("stream ended before successful login")
