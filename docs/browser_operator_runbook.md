# ToS_Companion browser operator runbook

## Purpose

This is the practical operating procedure for the joelab-hosted browser version.

The intended workflow is:

1. `tos-companion.service` runs continuously on joelab.
2. `companion_auth` remains the only Schwab OAuth/token owner.
3. Open ToS_Companion in a browser.
4. Select a stock, inspect live data/AE state, optionally run LLM analysis, and start recordings.
5. Closing the browser does not stop the backend, Schwab stream, or active recording.

## Before starting the service

Confirm the environment file contains:

```text
AUTH_HELPER_URL=http://companion-auth.p3l.co
TOS_COMPANION_HOST=127.0.0.1
TOS_COMPANION_PORT=8787
```

If server-side LLM analysis is desired, configure:

```text
OPENAI_API_KEY=...
```

Do not copy the Windows app's encrypted `openai_api_key` database value to joelab. AppState secrets are machine-bound and will not decrypt correctly on a different host.

Do not place Schwab access or refresh tokens in the ToS_Companion environment file.

## Start/check

```bash
sudo systemctl start tos-companion
sudo systemctl status tos-companion
journalctl -u tos-companion -n 100 --no-pager
```

Local health:

```bash
curl -sS http://127.0.0.1:8787/api/health
```

Expected shape:

```json
{
  "ok": true,
  "connection_state": "READY",
  "active_symbol": null,
  "auth_owner": "companion_auth"
}
```

Readiness:

```bash
curl -sS http://127.0.0.1:8787/api/readiness
```

This reports:
- whether companion_auth is authorized;
- whether the helper URL is configured;
- whether the LLM is configured;
- current DB path;
- recording root;
- current market-session mode.

It never returns Schwab access or refresh tokens.

## Schwab authorization

If readiness shows `companion_auth_authorized: false`, reauthorize through the existing companion_auth bootstrap process.

ToS_Companion must not create a separate Schwab OAuth session.

After companion_auth is healthy, refresh the browser or retry symbol selection.

## Browser workflow

### Load a stock

Enter a symbol and click **Load**.

This causes joelab to:
- fetch initial Schwab history;
- compute/seed AE context;
- establish the Schwab stream if needed;
- subscribe the symbol to L1;
- send state to the browser over WebSocket.

### Start a recording

Enter one or more comma-separated symbols in the recorder panel and click **Start**.

The server:
- uses the existing Schwab stream;
- expands the L1 subscription to all recording symbols;
- stores raw replay-grade L1 payloads per symbol;
- continues even if the browser closes;
- stops automatically at 3:00 PM ET.

Default recording path:

```text
~/.tos_companion/recordings/
```

### Run LLM analysis

Click **Run LLM** after a valid AE snapshot exists.

The request runs entirely on joelab. The browser never receives the OpenAI API key.

LLM analysis is manual in this browser foundation. Automatic polling/cadence is intentionally deferred.

## Updating code

From the joelab checkout:

```bash
git pull --ff-only
.venv/bin/pip install -e '.[web]'
sudo systemctl restart tos-companion
```

Then refresh the browser.

This is the main usability improvement over the old Windows workflow: no local rebuild/copy/relaunch cycle.

## Troubleshooting

### Browser loads but no live data

Check:

```bash
curl -sS http://127.0.0.1:8787/api/readiness
journalctl -u tos-companion -n 200 --no-pager
```

Common states:
- `AUTH_REQUIRED`: companion_auth needs authorization.
- `RECONNECTING`: Schwab stream is reconnecting.
- `DOWN` / `STREAM_DOWN`: stream retry budget exhausted.
- `READY`: backend is running but no live symbol has been selected yet.

### Browser disconnects

The browser WebSocket reconnects automatically.

A browser disconnect must not stop:
- the backend service;
- Schwab streaming;
- recording;
- server-side application state.

### Recorder stopped

The recorder stops automatically at 3:00 PM ET. Starting a new recorder after 3:00 PM ET is rejected.

### LLM button reports not configured

Set `OPENAI_API_KEY` in the joelab service environment and restart `tos-companion`.

## Not enabled yet

The browser foundation intentionally does not expose:
- live order submission;
- cancel/replace;
- flatten;
- account-management actions.

Those remain deferred until the read/analysis/recording path is proven live and access control is confirmed.
