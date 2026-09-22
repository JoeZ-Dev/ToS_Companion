#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/srv/apps/ToS_Companion}"
BRIDGE_DIR="${CODEX_BRIDGE_DIR:-/srv/data/tos-companion/codex-bridge}"
SERVICE_NAME="tos-companion-codex-bridge"
RUN_USER="${TOS_CODEX_USER:-$(id -un)}"
RUN_GROUP="${TOS_CODEX_GROUP:-$(id -gn)}"
CONTAINER_GID="${TOS_COMPANION_GID:-10001}"

cd "$REPO_DIR"

CODEX_BIN="${TOS_CODEX_BIN:-$(command -v codex || true)}"
PYTHON_BIN="${TOS_CODEX_PYTHON:-$(command -v python3 || true)}"

if [[ -z "$CODEX_BIN" ]]; then
  echo "ERROR: codex CLI is not on PATH for $RUN_USER." >&2
  exit 2
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: python3 is not available." >&2
  exit 3
fi
if ! "$CODEX_BIN" login status >/dev/null 2>&1; then
  echo "ERROR: codex CLI is not authenticated for $RUN_USER." >&2
  echo "Run: codex login" >&2
  exit 4
fi
if [[ ! -f deploy/codex_bridge.py || ! -f deploy/schemas/llm-analysis.schema.json ]]; then
  echo "ERROR: Codex bridge files are missing from $REPO_DIR." >&2
  exit 5
fi

echo "Preparing $BRIDGE_DIR for host user $RUN_USER and container GID $CONTAINER_GID..."
sudo install -d -o "$RUN_USER" -g "$CONTAINER_GID" -m 2770 "$BRIDGE_DIR"

tmp_unit="$(mktemp)"
trap 'rm -f "$tmp_unit"' EXIT
cat >"$tmp_unit" <<EOF
[Unit]
Description=ToS Companion host Codex CLI bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$REPO_DIR
Environment=TOS_CODEX_BIN=$CODEX_BIN
Environment=TOS_CODEX_REPO_DIR=$REPO_DIR
Environment=TOS_CODEX_SOCKET=$BRIDGE_DIR/bridge.sock
Environment=TOS_CODEX_SCHEMA=$REPO_DIR/deploy/schemas/llm-analysis.schema.json
Environment=TOS_CODEX_TIMEOUT_SECONDS=120
UMask=0007
ExecStart=$PYTHON_BIN $REPO_DIR/deploy/codex_bridge.py
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

sudo install -m 0644 "$tmp_unit" "/etc/systemd/system/$SERVICE_NAME.service"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

for _ in {1..20}; do
  [[ -S "$BRIDGE_DIR/bridge.sock" ]] && break
  sleep 0.25
done

if [[ ! -S "$BRIDGE_DIR/bridge.sock" ]]; then
  echo "ERROR: Codex bridge socket was not created." >&2
  sudo systemctl status "$SERVICE_NAME" --no-pager >&2 || true
  exit 6
fi

echo "Codex bridge ready: $BRIDGE_DIR/bridge.sock"
sudo systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,12p'
