# joelab Docker deployment

## Confirmed joelab topology

The live joelab ingress architecture is:

```text
Cloudflare Tunnel container
  cloudflared
      |
      | joelab-ingress Docker network
      |
      +--> companion-auth:8766
      |
      +--> tos-companion:8787
```

Both `cloudflared` and `companion-auth` are already attached to the external Docker network:

```text
joelab-ingress
```

ToS_Companion should use the same network.

No host port is required.

This avoids conflicts with other joelab services already using host ports, including the existing service bound to host port 8787.

## Schwab authentication

Inside Docker, ToS_Companion uses:

```text
AUTH_HELPER_URL=http://companion-auth:8766
```

`companion_auth` remains the sole owner of Schwab OAuth authorization and refresh tokens.

No Schwab token is copied into the ToS_Companion container.

## Build and start

From the ToS_Companion repository checkout:

```bash
cd /srv/apps/ToS_Companion
git fetch origin
git checkout feature/browser-server-foundation
git pull --ff-only

cp -n deploy/joelab.env.example deploy/joelab.env
docker compose \
  --env-file deploy/joelab.env \
  -f deploy/docker-compose.joelab.yml \
  up -d --build
```

Check status:

```bash
docker ps --filter name=tos-companion
docker logs --tail 100 tos-companion
docker inspect tos-companion --format '{{json .State.Health}}'
```

Check from another container on `joelab-ingress`:

```bash
docker run --rm --network joelab-ingress curlimages/curl:latest \
  -sS http://tos-companion:8787/api/health
```

Expected response includes:

```json
{
  "ok": true,
  "auth_owner": "companion_auth"
}
```

Readiness:

```bash
docker run --rm --network joelab-ingress curlimages/curl:latest \
  -sS http://tos-companion:8787/api/readiness
```

## Cloudflare Tunnel route

The current `cloudflared` container uses a tunnel token and has no local ingress configuration mounted.

That means public-hostname routing is managed in Cloudflare rather than in a local `config.yml`.

Recommended hostname:

```text
tos.p3l.co
```

Configure its tunnel service target as:

```text
http://tos-companion:8787
```

Because both containers share `joelab-ingress`, Cloudflare Tunnel can resolve the container name directly.

Do not route Cloudflare to:
- `127.0.0.1:8787`;
- a host-published 8787 port;
- `companion-auth`;
- a Schwab OAuth endpoint.

## Updating later

Once deployed, code updates are:

```bash
cd /srv/apps/ToS_Companion
git pull --ff-only

docker compose \
  --env-file deploy/joelab.env \
  -f deploy/docker-compose.joelab.yml \
  up -d --build
```

Then refresh the browser.

There is no Windows rebuild/copy/relaunch loop.

## Persistent data

The joelab deployment uses:
- the named volume `tos-companion-data` for recorder/session files at `/home/companion/.tos_companion`;
- the host bind path `/srv/data/tos-companion/state` for SQLite state, journal, and application state, mounted into `/home/companion/.local/share/MomentumTradingCompanion`.

The deployment helper creates `/srv/data/tos-companion/state` and assigns it to the container's non-root UID before startup. Runtime state therefore lives in joelab's standard `/srv/data` hierarchy and survives container replacement and rebuilds.

## LLM integration: host Codex CLI bridge

The joelab/browser runtime does not use `OPENAI_API_KEY`.

It follows the same host-authenticated Codex CLI pattern used by the newer Fred runtime:

```text
browser
  -> tos-companion container
     -> Unix socket /run/tos-codex/bridge.sock
        -> host bridge running as joe
           -> authenticated codex exec
        <- strict structured JSON
     <- existing deterministic ToS LLM validation
```

Codex credentials stay on the joelab host and are never mounted into Docker or sent to the browser. The bridge uses an ephemeral, read-only Codex execution with a finite timeout and a checked-in output schema.

After pulling the branch, install or refresh the host service while logged in as the user whose Codex CLI is authenticated:

```bash
cd /srv/apps/ToS_Companion
codex login status
bash deploy/install_codex_bridge.sh
```

The installer creates `/srv/data/tos-companion/codex-bridge`, installs a systemd service running as the current host user, and starts the bridge. Docker mounts that directory at `/run/tos-codex`.

Expected readiness includes `"llm_configured": true` and `"llm_provider": "codex_cli_bridge"`.

The existing direct HTTP/API-key client remains in the codebase only for desktop compatibility and tests; the joelab browser runtime no longer selects it.

## Browser order controls

Live order submission remains intentionally unavailable in the first browser deployment.

The first live deployment validates:
- companion_auth connectivity;
- Schwab history/stream;
- chart;
- AE state;
- WebSocket continuity;
- recorder persistence;
- optional manual LLM analysis.


## Recorder acceptance test

After deployment, validate that recording is owned by the server rather than by an open browser session:

```bash
cd /srv/apps/ToS_Companion
RECORD_SECONDS=60 bash deploy/validate_recorder.sh IMCC,LHSW
```

The script:
1. starts recording through the server API;
2. exits the request immediately, with no browser connection kept open;
3. waits while the joelab backend continues recording;
4. confirms recorder state is still active;
5. stops recording;
6. verifies the manifest and per-symbol JSONL line counts agree;
7. fails if no raw `LEVELONE_EQUITIES` events were persisted.

Use symbols that are actively receiving quote updates during the test.


## Early premarket history behavior

Live validation on 2026-09-22 showed an important Schwab distinction:

- the live LEVELONE_EQUITIES stream can deliver updates before 7:00 AM ET;
- Schwab REST 1-minute price history returned no candles before 7:00 AM ET;
- after 7:00 AM ET, the same intraday history request began returning minute candles.

To preserve the 4:00-7:00 AM window, ToS_Companion can reconstruct 1-minute fallback candles from its own persisted LEVELONE_EQUITIES recordings. The runtime and AE seed paths merge those fallback candles with Schwab REST history.

Merge rule:

```text
Schwab REST candle wins on an overlapping minute.
Recorder-derived candle fills only a missing minute.
```

This does not manufacture history. A 4:00-7:00 AM minute can only be reconstructed for a symbol that ToS_Companion was actually recording while those raw L1 events occurred.
