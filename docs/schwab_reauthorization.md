# Secure Schwab reauthorization

## Existing ownership and trust boundary

The deployed `companion_auth` service is the sole Schwab OAuth owner. Before
this change its API was:

| Endpoint | Boundary | Purpose |
|---|---|---|
| `GET /health` | public | liveness only |
| `GET /access_token` | `X-Internal-Auth` shared secret | vend a short-lived access token |

It atomically owns `/data/tokens.json`, including the refresh token, and keeps
`SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET`, and `INTERNAL_AUTH_SECRET` in its
private deployment environment. ToS_Companion receives only a short-lived
access token over the private `joelab-ingress` network. This change does not
create another token store or accept Schwab credentials in ToS_Companion.

The existing public `tos.p3l.co` route was anonymously reachable on 2026-10-08,
despite older deployment documentation describing an access-control layer.
Reauthorization therefore cannot safely trust mere reachability of the web UI.
The mutation endpoints fail closed and validate a signed Cloudflare Access JWT,
its application audience, issuer, expiration, and an explicit admin email
allowlist. A forged `Cf-Access-Jwt-Assertion` header does not pass signature
validation.

## Companion-auth extension

The companion-auth PR extends that same service with:

| Endpoint | Boundary | Purpose |
|---|---|---|
| `POST /oauth/authorize` | `X-Internal-Auth` | create a 180-second OAuth transaction and return Schwab's official URL |
| `GET /oauth/status/{flow_id}` | `X-Internal-Auth` | return redacted transaction state |
| `GET /callback` | public, state-gated | consume state once, exchange server-side, atomically replace tokens |

Outstanding state is random, single-use, memory-only, and expires after three
minutes. Unsolicited, mismatched, expired, and duplicate callbacks are rejected.
The installed schwab-py client validates OAuth state but does not expose PKCE
verifier/challenge support, so the implementation reuses its supported flow
instead of inventing a parallel OAuth client. If that existing client gains
PKCE support, companion-auth is the only component that should adopt it.

The callback never returns tokens or codes. Its page immediately removes the
query string from browser history. Uvicorn access logging is disabled on
companion-auth because access logs otherwise include the callback query. OAuth
failure logs contain an opaque flow ID only and deliberately omit exception
tracebacks that could embed the received URL.

## ToS_Companion workflow

The browser calls only the ToS backend. The backend uses its existing
`INTERNAL_AUTH_SECRET` to start and poll companion-auth. After companion-auth
finishes the exchange, ToS_Companion:

1. invalidates its old helper-token cache;
2. requires a fresh successful `/access_token` response;
3. performs the existing read-only Schwab `userPreference` request;
4. verifies streamer metadata is present;
5. replaces the stream connection and waits for a successful stream LOGIN;
6. reports `Connected` and records the recovery timestamp.

It does not select symbols, enable a policy, change detectors or thresholds,
place trades, or start a recording session. An already-open recorder continues
through the normal stream reconnection. If an outage interrupted a recorder and
no recorder remains at recovery, the UI shows an explicit **Resume recording**
control; only clicking it may start a new session.

Authorization continuity is append-only at
`~/.tos_companion/authorization_continuity.jsonl`. Rows contain only outage or
recovery timestamp and whether recording was active; they contain no outcomes.

## Required deployment configuration

Configure Cloudflare Access for the administrative browser identity, then set:

```text
TOS_CLOUDFLARE_ACCESS_TEAM_DOMAIN=your-team.cloudflareaccess.com
TOS_CLOUDFLARE_ACCESS_AUD=<application-audience-tag>
TOS_ADMIN_EMAILS=owner@example.com
```

All three are required. Missing or invalid configuration returns `403` for
reauthorization and resume mutations. Read-only status remains available so an
anonymous viewer may see that authorization is required but cannot replace the
Schwab account authorization.

Do not add Schwab usernames, passwords, client secrets, access tokens, refresh
tokens, or authorization codes to these variables, browser storage, URLs, or
ToS_Companion logs.
