from __future__ import annotations

import json
from pathlib import Path
import socket
import threading

from momentum_companion.llm.codex_bridge_client import CodexBridgeClient


def _serve_once(path: Path, response: dict, captured: list[dict], ready: threading.Event) -> None:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    ready.set()
    conn, _ = server.accept()
    with conn:
        chunks = []
        while True:
            chunk = conn.recv(65_536)
            if not chunk:
                break
            chunks.append(chunk)
        captured.append(json.loads(b"".join(chunks).decode("utf-8")))
        conn.sendall(json.dumps(response).encode("utf-8"))
    server.close()


def test_codex_bridge_client_returns_structured_result(tmp_path: Path):
    path = tmp_path / "bridge.sock"
    captured: list[dict] = []
    ready = threading.Event()
    result = {"stock_bias": "NO_EDGE", "summary": "No setup.", "setups": []}
    thread = threading.Thread(
        target=_serve_once,
        args=(path, {"ok": True, "provider": "codex_cli", "result": result}, captured, ready),
        daemon=True,
    )
    thread.start()
    assert ready.wait(2)

    client = CodexBridgeClient(path, timeout_seconds=2)
    actual = client.complete([{"role": "user", "content": "analyze"}], model_override="legacy-model")

    thread.join(timeout=2)
    assert actual == result
    assert captured[0]["type"] == "complete"
    assert captured[0]["messages"][0]["content"] == "analyze"
    assert "model" not in captured[0]


def test_codex_bridge_client_status_drives_availability(tmp_path: Path):
    path = tmp_path / "bridge.sock"
    captured: list[dict] = []
    ready = threading.Event()
    thread = threading.Thread(
        target=_serve_once,
        args=(path, {"ok": True, "provider": "codex_cli", "authenticated": True}, captured, ready),
        daemon=True,
    )
    thread.start()
    assert ready.wait(2)

    client = CodexBridgeClient(path, timeout_seconds=2)
    assert client.is_available() is True

    thread.join(timeout=2)
    assert captured[0] == {"type": "status"}
