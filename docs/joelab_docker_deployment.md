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

## LLM integration direction

The current browser foundation still contains the legacy direct OpenAI API-key client, but this is transitional only.

The joelab/browser implementation is planned to move to the same CLI-style OpenAI authentication/execution pattern used by the user's newer applications, rather than requiring a long-lived `OPENAI_API_KEY` in `deploy/joelab.env`.

Until that refactor is implemented and validated, browser LLM analysis should be treated as optional and may remain unconfigured. Do not migrate the encrypted desktop API-key secret to joelab; AppState encryption is machine-bound.

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
