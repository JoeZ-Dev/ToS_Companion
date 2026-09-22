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

The compose project uses the named volume:

```text
tos-companion-data
```

mounted at:

```text
/home/companion/.tos_companion
```

This persists:
- SQLite state/journal data;
- recordings;
- application state

across container rebuilds.

## OpenAI key

If browser-side manual LLM analysis is desired, set `OPENAI_API_KEY` in:

```text
deploy/joelab.env
```

Do not copy the encrypted desktop database secret to joelab because AppState encryption is machine-bound.

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
