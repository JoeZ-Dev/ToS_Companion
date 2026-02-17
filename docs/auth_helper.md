Auth Helper (Homelab)
=====================

Purpose
-------
Provide Schwab access tokens to the Windows app without storing Schwab client secrets on the Windows machine. The homelab hosts a tiny helper that holds `SCHWAB_CLIENT_ID/SECRET`, manages tokens, and serves short-lived access tokens over HTTP.

How it works
------------
- Run the helper on homelab: `python -m tools.auth_helper.server`
- Endpoints:
  - `GET /health` → `{"ok": true}`
  - `GET /access_token` → `{"access_token": "...", "expires_at": <unix>, "source": "homelab"}`
  - If no `refresh_token` exists, `/access_token` returns HTTP 409 with instructions to run the bootstrap script.
- Token storage: defaults to platform config dir (e.g., `%APPDATA%/MomentumTradingCompanion/tokens.json` on Windows; `~/.config/MomentumTradingCompanion/tokens.json` on Linux). Override with `AUTH_HELPER_TOKEN_PATH`.
- The helper refreshes tokens with Schwab when <60s remaining. Client secrets are never logged or returned.

Env vars on homelab
-------------------
- `SCHWAB_CLIENT_ID` (required)
- `SCHWAB_CLIENT_SECRET` (required)
- `SCHWAB_REDIRECT_URI` (optional; default `https://companion-auth.p3l.co/callback`)
- `AUTH_HELPER_BIND` (default `0.0.0.0`)
- `AUTH_HELPER_PORT` (default `8766`)
- `AUTH_HELPER_TOKEN_PATH` (optional override for tokens.json)

Bootstrap (one-time OAuth)
--------------------------
If `/access_token` returns 409, perform interactive OAuth on homelab:
```
python -m tools.auth_helper.bootstrap
```
- Follow the printed URL, approve the app, and the script writes tokens to `AUTH_HELPER_TOKEN_PATH` (or default path).

Windows app usage
-----------------
- Set `AUTH_HELPER_URL` on Windows to point at homelab, e.g., `http://homelab:8766`.
- The app will GET `/access_token`, cache the token until near expiry, and never require `SCHWAB_CLIENT_ID/SECRET` locally.
- If the helper returns an error/409, the app sets state `AUTH_REQUIRED` and does not crash.

Files
-----
- `tools/auth_helper/server.py` — runs the helper service.
- `tools/auth_helper/bootstrap.py` — one-time OAuth to create refreshable tokens on homelab.
- `tools/auth_helper/tokens.py` — token load/save/refresh utilities (used by helper).
