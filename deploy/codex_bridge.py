#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile

SOCKET_PATH = Path(os.environ.get("TOS_CODEX_SOCKET", "/srv/data/tos-companion/codex-bridge/bridge.sock"))
REPO_DIR = Path(os.environ.get("TOS_CODEX_REPO_DIR", "/srv/apps/ToS_Companion"))
SCHEMA_PATH = Path(os.environ.get("TOS_CODEX_SCHEMA", str(REPO_DIR / "deploy" / "schemas" / "llm-analysis.schema.json")))
CODEX_BIN = os.environ.get("TOS_CODEX_BIN") or shutil.which("codex") or "codex"
TIMEOUT_SECONDS = float(os.environ.get("TOS_CODEX_TIMEOUT_SECONDS", "120"))
MAX_REQUEST_BYTES = 1_048_576


def _send(conn: socket.socket, payload: dict) -> None:
    conn.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _codex_authenticated() -> bool:
    try:
        proc = subprocess.run(
            [CODEX_BIN, "login", "status"],
            cwd=REPO_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _build_prompt(messages: list[dict]) -> str:
    parts = [
        "You are the reasoning provider for ToS_Companion.",
        "This is advisory market analysis only. Never place, modify, or cancel orders.",
        "Return only the structured JSON required by the supplied output schema.",
    ]
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").upper()
        content = message.get("content")
        if isinstance(content, str):
            parts.append(f"{role}:\n{content}")
    return "\n\n".join(parts)


def _complete(messages: list[dict]) -> dict:
    if not _codex_authenticated():
        raise RuntimeError("codex_cli_not_authenticated")
    if not SCHEMA_PATH.is_file():
        raise RuntimeError("codex_output_schema_missing")

    with tempfile.TemporaryDirectory(prefix="tos-codex-") as tmp:
        result_path = Path(tmp) / "result.json"
        proc = subprocess.run(
            [
                CODEX_BIN,
                "exec",
                "-s",
                "read-only",
                "--ephemeral",
                "--json",
                "-C",
                str(REPO_DIR),
                "--output-schema",
                str(SCHEMA_PATH),
                "--output-last-message",
                str(result_path),
                "-",
            ],
            input=_build_prompt(messages),
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().replace("\n", " ")[:400]
            raise RuntimeError(f"codex_exec_failed:{proc.returncode}:{detail}")
        if not result_path.is_file() or result_path.stat().st_size == 0:
            raise RuntimeError("codex_cli_empty_result")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise RuntimeError("codex_result_not_object")
        return result


def _read_request(conn: socket.socket) -> dict:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = conn.recv(65_536)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_REQUEST_BYTES:
            raise RuntimeError("request_too_large")
        chunks.append(chunk)
    if not chunks:
        raise RuntimeError("empty_request")
    request = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(request, dict):
        raise RuntimeError("request_not_object")
    return request


def _handle(conn: socket.socket) -> None:
    try:
        request = _read_request(conn)
        kind = request.get("type")
        if kind == "status":
            _send(conn, {"ok": True, "provider": "codex_cli", "authenticated": _codex_authenticated()})
            return
        if kind != "complete":
            raise RuntimeError("unsupported_request_type")
        messages = request.get("messages")
        if not isinstance(messages, list):
            raise RuntimeError("messages_required")
        _send(conn, {"ok": True, "provider": "codex_cli", "result": _complete(messages)})
    except subprocess.TimeoutExpired:
        _send(conn, {"ok": False, "error": "codex_cli_timed_out"})
    except Exception as exc:
        _send(conn, {"ok": False, "error": str(exc)[:500]})


def main() -> int:
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOCKET_PATH.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCKET_PATH))
    os.chmod(SOCKET_PATH, 0o660)
    server.listen(8)

    def cleanup(*_args) -> None:
        try:
            server.close()
        finally:
            SOCKET_PATH.unlink(missing_ok=True)
            raise SystemExit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    try:
        while True:
            conn, _ = server.accept()
            with conn:
                _handle(conn)
    finally:
        server.close()
        SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
