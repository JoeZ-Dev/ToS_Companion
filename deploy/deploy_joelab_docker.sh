#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/srv/apps/ToS_Companion}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.joelab.yml}"
ENV_FILE="${ENV_FILE:-deploy/joelab.env}"
STATE_DIR="${STATE_DIR:-/srv/data/tos-companion/state}"
CODEX_BRIDGE_DIR="${CODEX_BRIDGE_DIR:-/srv/data/tos-companion/codex-bridge}"

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

echo "Preparing host Codex bridge directory at $CODEX_BRIDGE_DIR..."
sudo install -d -o "$(id -u)" -g 10001 -m 2770 "$CODEX_BRIDGE_DIR"

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
mounts_json="$(docker inspect tos-companion --format '{{json .Mounts}}')"
python3 - "$STATE_DIR" "$CODEX_BRIDGE_DIR" <<'PY' <<<"$mounts_json"
import json
import sys

state_dir = sys.argv[1]
codex_dir = sys.argv[2]
mounts = json.load(sys.stdin)

by_destination = {
    mount.get("Destination"): mount
    for mount in mounts
    if isinstance(mount, dict) and mount.get("Destination")
}

recordings = by_destination.get("/home/companion/.tos_companion")
if recordings is None:
    raise SystemExit(
        "ERROR: recordings persistence mount is missing at "
        "/home/companion/.tos_companion"
    )

state = by_destination.get(
    "/home/companion/.local/share/MomentumTradingCompanion"
)
if state is None:
    raise SystemExit(
        "ERROR: runtime state mount destination is missing."
    )
if state.get("Type") != "bind" or state.get("Source") != state_dir:
    raise SystemExit(
        "ERROR: runtime state mount mismatch: "
        f"type={state.get('Type')!r} source={state.get('Source')!r} "
        f"expected_source={state_dir!r}"
    )

codex = by_destination.get("/run/tos-codex")
if codex is None:
    raise SystemExit("ERROR: Codex bridge mount destination is missing.")
if codex.get("Type") != "bind" or codex.get("Source") != codex_dir:
    raise SystemExit(
        "ERROR: Codex bridge mount mismatch: "
        f"type={codex.get('Type')!r} source={codex.get('Source')!r} "
        f"expected_source={codex_dir!r}"
    )

print("Persistent mounts verified.")
PY

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

if ! python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("llm_configured") else 1)' <<<"$readiness_json"; then
  echo "WARNING: host Codex CLI bridge is not available; Run LLM will remain disabled until it is installed/authenticated." >&2
fi

echo
echo "Deployment complete."
echo "Cloudflare Tunnel target should be: http://tos-companion:8787"
