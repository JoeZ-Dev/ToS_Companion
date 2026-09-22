#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/srv/apps/ToS_Companion}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.joelab.yml}"
ENV_FILE="${ENV_FILE:-deploy/joelab.env}"
STATE_DIR="${STATE_DIR:-/srv/data/tos-companion/state}"

cd "$REPO_DIR"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: missing $REPO_DIR/$COMPOSE_FILE" >&2
  exit 2
fi

if ! docker network inspect joelab-ingress >/dev/null 2>&1; then
  echo "ERROR: required external Docker network joelab-ingress does not exist." >&2
  exit 3
fi

if ! docker inspect companion-auth >/dev/null 2>&1; then
  echo "ERROR: companion-auth container is not present." >&2
  exit 4
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp deploy/joelab.env.example "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE from the example."
fi

echo "Preparing persistent runtime state at $STATE_DIR..."
sudo mkdir -p "$STATE_DIR"
sudo chown 10001:10001 "$STATE_DIR"

echo "Validating compose configuration..."
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null

echo "Building and starting ToS_Companion..."
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build

echo "Waiting for container health..."
for _ in {1..30}; do
  status="$(docker inspect tos-companion --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || true)"
  case "$status" in
    healthy)
      break
      ;;
    unhealthy)
      echo "ERROR: tos-companion healthcheck failed." >&2
      docker logs --tail 200 tos-companion >&2 || true
      exit 5
      ;;
  esac
  sleep 1
done

status="$(docker inspect tos-companion --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || true)"
if [[ "$status" != "healthy" ]]; then
  echo "ERROR: tos-companion did not become healthy; status=$status" >&2
  docker logs --tail 200 tos-companion >&2 || true
  exit 6
fi

echo "Verifying persistent mounts..."
mount_pairs="$(
  docker inspect tos-companion     --format '{{range .Mounts}}{{println .Source " -> " .Destination}}{{end}}'
)"
if ! grep -Fq ' -> /home/companion/.tos_companion' <<<"$mount_pairs"; then
  echo "ERROR: recordings persistence mount is missing." >&2
  exit 7
fi
if ! grep -Fqx "$STATE_DIR -> /home/companion/.local/share/MomentumTradingCompanion" <<<"$mount_pairs"; then
  echo "ERROR: runtime state is not bound from $STATE_DIR." >&2
  exit 8
fi

echo "Checking internal ingress-network health..."
health_json="$(
  docker run --rm --network joelab-ingress curlimages/curl:latest     --fail --silent --show-error http://tos-companion:8787/api/health
)"
echo "$health_json"

echo
echo "Checking readiness (including companion_auth)..."
readiness_json="$(
  docker run --rm --network joelab-ingress curlimages/curl:latest     --fail --silent --show-error http://tos-companion:8787/api/readiness
)"
echo "$readiness_json"

echo
echo "Deployment complete."
echo "Cloudflare Tunnel target should be: http://tos-companion:8787"
