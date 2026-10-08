from __future__ import annotations

import json
import threading
import base64
import time

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from momentum_companion.clients.companion_auth import (
    CompanionAuthClient,
    CompanionAuthError,
)
from momentum_companion.recording.auth_continuity import AuthorizationContinuityJournal
from momentum_companion.runtime import CompanionRuntime
from momentum_companion.session import CompanionSession
from momentum_companion.web.admin_access import AdminAccessVerifier


class SequenceTransport(httpx.BaseTransport):
    def __init__(self, responses):
        self.responses = list(responses)

    def handle_request(self, request):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(item[0], json=item[1], request=request)


def auth_client(responses):
    http = httpx.Client(transport=SequenceTransport(responses))
    return CompanionAuthClient("http://companion-auth:8766", "shared", client=http)


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def test_admin_access_requires_valid_signed_allowlisted_identity():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "key-1",
        "e": b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
        "n": b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
    }
    certs = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"keys": [jwk]}, request=request)
    ))
    verifier = AdminAccessVerifier(
        team_domain="team.cloudflareaccess.com",
        audience="admin-app",
        admin_emails="owner@example.com",
        client=certs,
    )
    header = b64(json.dumps({"alg": "RS256", "kid": "key-1"}).encode())
    payload = b64(json.dumps({
        "iss": "https://team.cloudflareaccess.com",
        "aud": ["admin-app"],
        "email": "owner@example.com",
        "exp": int(time.time()) + 60,
    }).encode())
    signature = b64(private.sign(
        f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256()
    ))
    assert verifier.authorize(f"{header}.{payload}.{signature}") is True
    assert verifier.authorize(f"{header}.{payload}.tampered") is False
    assert AdminAccessVerifier(team_domain="", audience="", admin_emails="").authorize(None) is False


def test_companion_auth_client_starts_and_polls_redacted_flow():
    client = auth_client([
        (200, {
            "authorization_url": "https://api.schwabapi.com/v1/oauth/authorize?state=opaque",
            "flow_id": "flow-1",
            "expires_at": 123,
        }),
        (200, {"status": "waiting", "expires_at": 123}),
    ])
    started = client.start_authorization()
    status = client.authorization_status(started["flow_id"])
    assert started["authorization_url"].startswith("https://api.schwabapi.com/")
    assert status == {"status": "waiting", "expires_at": 123}
    assert "access_token" not in json.dumps({**started, **status})


def test_companion_auth_client_rejects_non_schwab_url_and_unavailability():
    bad = auth_client([(200, {
        "authorization_url": "https://evil.example/authorize",
        "flow_id": "flow-1",
    })])
    try:
        bad.start_authorization()
    except CompanionAuthError as exc:
        assert "invalid authorization URL" in str(exc)
    else:
        raise AssertionError("non-Schwab URL accepted")

    unavailable = auth_client([httpx.ConnectError("secret-internal-detail")])
    try:
        unavailable.start_authorization()
    except CompanionAuthError as exc:
        assert str(exc) == "companion_auth is unavailable"
        assert "secret-internal-detail" not in str(exc)
    else:
        raise AssertionError("unavailable companion_auth accepted")


class FakeCompanionAuth:
    def __init__(self, statuses):
        self.statuses = list(statuses)

    def start_authorization(self):
        return {
            "authorization_url": "https://api.schwabapi.com/v1/oauth/authorize?state=opaque",
            "flow_id": "flow-1",
            "expires_at": 123,
        }

    def authorization_status(self, _flow_id):
        return self.statuses.pop(0)


class FakeTokenProvider:
    _auth_helper_url = "http://companion-auth:8766"

    def __init__(self):
        self.fresh_fetches = 0

    def fetch_fresh_helper_token(self):
        self.fresh_fetches += 1
        return "short-lived-secret"


class FakeRest:
    def __init__(self):
        self.preference_calls = 0

    def get_user_preference(self):
        self.preference_calls += 1
        return {"streamerInfo": [{"streamerSocketUrl": "wss://stream.example"}]}


def runtime_for_auth(tmp_path):
    runtime = CompanionRuntime.__new__(CompanionRuntime)
    runtime.session = CompanionSession()
    runtime._lock = threading.RLock()
    runtime._stream = None
    runtime._recorder = None
    runtime._recording_symbols = set()
    runtime._analysis_symbols = {"EXISTING"}
    runtime.token_provider = FakeTokenProvider()
    runtime.rest = FakeRest()
    runtime.companion_auth = FakeCompanionAuth([{"status": "authorized", "expires_at": 123}])
    runtime._auth_continuity = AuthorizationContinuityJournal(tmp_path / "continuity.jsonl")
    runtime._auth_workflow_state = "authorization_required"
    runtime._auth_flow_id = None
    runtime._auth_flow_expires_at = None
    runtime._auth_error = None
    runtime._auth_outage_open = False
    runtime._recording_active_at_outage = False
    runtime._resume_recording_required = False
    runtime._refresh_stream_subscription = lambda: None
    runtime._ensure_stream = lambda: setattr(runtime, "_stream", object())
    return runtime


def test_success_requires_read_only_confirmation_and_stream_readiness(tmp_path):
    runtime = runtime_for_auth(tmp_path)
    started = runtime.begin_schwab_reauthorization()
    verified = runtime.poll_schwab_reauthorization()

    assert started["status"] == "waiting"
    assert verified["status"] == "authorized_reconnecting"
    assert runtime.token_provider.fresh_fetches == 1
    assert runtime.rest.preference_calls == 1
    assert runtime._analysis_symbols == {"EXISTING"}
    assert runtime._recorder is None

    runtime._on_stream_state("CONNECTED")
    connected = runtime.poll_schwab_reauthorization()
    assert connected["status"] == "connected"
    assert connected["authorized"] is True
    events = runtime._auth_continuity.read()
    assert [item["event"] for item in events] == [
        "authorization_outage", "authorization_recovered"
    ]


def test_failed_read_only_confirmation_never_reports_authorized(tmp_path):
    runtime = runtime_for_auth(tmp_path)

    def fail():
        runtime.rest.preference_calls += 1
        raise RuntimeError("Bearer secret-token")

    runtime.rest.get_user_preference = fail
    runtime.begin_schwab_reauthorization()
    status = runtime.poll_schwab_reauthorization()
    assert status["status"] == "failed"
    assert status["authorized"] is False
    assert "secret-token" not in status["error"]


def test_callback_failure_and_expiry_are_retryable_without_behavior_changes(tmp_path):
    for upstream in (
        {"status": "failed", "error": "Authorization was declined."},
        {"status": "expired", "error": "Authorization request expired. Please retry."},
    ):
        runtime = runtime_for_auth(tmp_path)
        runtime.companion_auth = FakeCompanionAuth([upstream])
        runtime.begin_schwab_reauthorization()
        status = runtime.poll_schwab_reauthorization()
        assert status["status"] == "failed"
        assert status["authorized"] is False
        assert runtime._analysis_symbols == {"EXISTING"}
        assert runtime._recorder is None
