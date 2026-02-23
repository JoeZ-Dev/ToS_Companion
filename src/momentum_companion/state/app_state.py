from __future__ import annotations

import sqlite3
from typing import Any, Optional
from cryptography.fernet import Fernet, InvalidToken
import base64
import hashlib
import platform
import os


class AppStateStore:
    """Handles app_state table reads/writes and persistence toggles (§7.2)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def get(self, key: str) -> Optional[str]:
        """Retrieve a stored value."""
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("SELECT value FROM app_state WHERE key=?", (key,))
            row = cur.fetchone()
            return row[0] if row else None

    def set(self, key: str, value: Any) -> None:
        """Persist a value."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO app_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            conn.commit()

    def set_secret(self, key: str, value: str) -> None:
        """Persist a lightly encrypted value."""
        if value is None:
            return
        encoded = self._fernet_encode(value)
        self.set(key, encoded)

    def get_secret(self, key: str) -> Optional[str]:
        """Retrieve and decrypt a secret value."""
        enc = self.get(key)
        if enc is None:
            return None
        try:
            return self._fernet_decode(enc)
        except Exception:
            return None

    def _fernet_encode(self, plaintext: str) -> str:
        f = self._fernet()
        token = f.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def _fernet_decode(self, encoded: str) -> str:
        f = self._fernet()
        try:
            data = f.decrypt(encoded.encode("utf-8"))
            return data.decode("utf-8")
        except InvalidToken:
            # fallback to legacy xor if old entries exist
            return self._xor_legacy_decode(encoded)

    def _fernet(self) -> Fernet:
        key = self._derive_key()
        return Fernet(key)

    def _xor_legacy_decode(self, encoded: str) -> str:
        key_bytes = hashlib.sha256(platform.node().encode("utf-8")).digest()
        data = base64.urlsafe_b64decode(encoded.encode("utf-8"))
        out = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data)])
        return out.decode("utf-8")

    @staticmethod
    def _derive_key() -> bytes:
        # derive a stable machine-bound key; pad/trim to 32 bytes for Fernet
        h = hashlib.sha256(platform.node().encode("utf-8")).digest()
        return base64.urlsafe_b64encode(h)
