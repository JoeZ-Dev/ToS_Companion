from __future__ import annotations

import base64
import json
import os
import threading
import time
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class AdminAccessVerifier:
    """Validate Cloudflare Access JWTs for authorization-changing actions.

    The public application remains readable. OAuth mutation endpoints fail
    closed unless Access audience, team domain, and an explicit admin email
    allowlist are all configured and the signed assertion validates.
    """

    def __init__(self, *, team_domain: str | None = None,
                 audience: str | None = None, admin_emails: str | None = None,
                 client: httpx.Client | None = None,
                 now_fn=time.time) -> None:
        raw_domain = team_domain if team_domain is not None else os.getenv(
            "TOS_CLOUDFLARE_ACCESS_TEAM_DOMAIN", ""
        )
        self.team_domain = raw_domain.strip().removeprefix("https://").rstrip("/")
        self.audience = (
            audience if audience is not None
            else os.getenv("TOS_CLOUDFLARE_ACCESS_AUD", "")
        ).strip()
        raw_emails = (
            admin_emails if admin_emails is not None
            else os.getenv("TOS_ADMIN_EMAILS", "")
        )
        self.admin_emails = {
            value.strip().lower() for value in raw_emails.split(",") if value.strip()
        }
        self._client = client or httpx.Client(timeout=5.0, trust_env=False)
        self._now = now_fn
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._keys_expire_at = 0.0
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.team_domain and self.audience and self.admin_emails)

    def authorize(self, assertion: str | None) -> bool:
        if not self.configured or not assertion:
            return False
        try:
            encoded_header, encoded_payload, encoded_signature = assertion.split(".")
            header = json.loads(self._decode(encoded_header))
            payload = json.loads(self._decode(encoded_payload))
            if header.get("alg") != "RS256" or not header.get("kid"):
                return False
            key = self._key(str(header["kid"]))
            key.verify(
                self._decode_bytes(encoded_signature),
                f"{encoded_header}.{encoded_payload}".encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            now = int(self._now())
            if int(payload.get("exp", 0)) <= now:
                return False
            if int(payload.get("nbf", 0) or 0) > now:
                return False
            aud = payload.get("aud") or []
            if isinstance(aud, str):
                aud = [aud]
            if self.audience not in aud:
                return False
            expected_issuer = f"https://{self.team_domain}"
            if payload.get("iss") != expected_issuer:
                return False
            email = str(payload.get("email") or "").lower()
            return email in self.admin_emails
        except Exception:
            return False

    def _key(self, kid: str) -> rsa.RSAPublicKey:
        with self._lock:
            if self._now() >= self._keys_expire_at or kid not in self._keys:
                response = self._client.get(
                    f"https://{self.team_domain}/cdn-cgi/access/certs"
                )
                response.raise_for_status()
                keys: dict[str, rsa.RSAPublicKey] = {}
                for item in response.json().get("keys") or []:
                    if item.get("kty") != "RSA" or not item.get("kid"):
                        continue
                    keys[str(item["kid"])] = rsa.RSAPublicNumbers(
                        e=int.from_bytes(self._decode_bytes(str(item["e"])), "big"),
                        n=int.from_bytes(self._decode_bytes(str(item["n"])), "big"),
                    ).public_key()
                self._keys = keys
                self._keys_expire_at = self._now() + 3600
            return self._keys[kid]

    @staticmethod
    def _decode(value: str) -> str:
        return AdminAccessVerifier._decode_bytes(value).decode()

    @staticmethod
    def _decode_bytes(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
