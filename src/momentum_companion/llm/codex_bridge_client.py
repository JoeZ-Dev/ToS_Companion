from __future__ import annotations

import json
from pathlib import Path
import socket
from typing import Any


class CodexBridgeError(RuntimeError):
    pass


class CodexBridgeClient:
    """Client for the host-authenticated Codex CLI Unix-socket bridge."""

    def __init__(
        self,
        socket_path: str | Path = "/run/tos-codex/bridge.sock",
        *,
        timeout_seconds: float = 120.0,
        max_response_bytes: int = 1_048_576,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = int(max_response_bytes)

    def complete(
        self,
        messages: list[dict[str, str]],
        model_override: str | None = None,
    ) -> dict[str, Any]:
        # The host bridge owns model selection; legacy desktop model names
        # deliberately do not cross this provider boundary.
        response = self._request({"type": "complete", "messages": messages})
        result = response.get("result")
        if not isinstance(result, dict):
            raise CodexBridgeError("Codex bridge returned no structured result")
        return result

    def status(self) -> dict[str, Any]:
        return self._request({"type": "status"}, timeout_seconds=5.0)

    def is_available(self) -> bool:
        try:
            return bool(self.status().get("authenticated"))
        except (OSError, ValueError, CodexBridgeError):
            return False

    def _request(
        self,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        raw = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        if len(raw) > 1_048_576:
            raise CodexBridgeError("Codex bridge request is too large")

        chunks: list[bytes] = []
        total = 0
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_seconds or self.timeout_seconds)
            sock.connect(str(self.socket_path))
            sock.sendall(raw)
            sock.shutdown(socket.SHUT_WR)
            while True:
                chunk = sock.recv(65_536)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_response_bytes:
                    raise CodexBridgeError("Codex bridge response is too large")
                chunks.append(chunk)

        if not chunks:
            raise CodexBridgeError("Codex bridge returned an empty response")
        response = json.loads(b"".join(chunks).decode("utf-8"))
        if not isinstance(response, dict):
            raise CodexBridgeError("Codex bridge returned an invalid response")
        if not response.get("ok"):
            raise CodexBridgeError(str(response.get("error") or "Codex bridge failed"))
        return response
