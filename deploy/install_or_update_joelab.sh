#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/apps/tos-companion}"
SERVICE_NAME="${SERVICE_NAME:-tos-companion}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"

if [[ ! -f "$APP_DIR/pyproject.toml" ]]; then
  echo "ERROR: APP_DIR does not contain a ToS_Companion checkout: $APP_DIR" >&2
  exit 2
fi

cd "$APP_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -e '.[web]'

if [[ ! -f "$ENV_FILE" ]]; then
  cp deploy/tos-companion.env.example "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE from example. Review it before starting the service."
fi

UNIT_SOURCE="$APP_DIR/deploy/systemd/tos-companion.service.example"
UNIT_TARGET="/etc/systemd/system/${SERVICE_NAME}.service"

if command -v sudo >/dev/null 2>&1; then
  sudo cp "$UNIT_SOURCE" "$UNIT_TARGET"
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME"
  sudo systemctl restart "$SERVICE_NAME"
else
  echo "ERROR: sudo is required to install/restart the systemd service." >&2
  exit 3
fi

sleep 1
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

if "$VENV_DIR/bin/python" tools/check_web_readiness.py; then
  echo "ToS_Companion web service is ready."
else
  rc=$?
  echo "Service started but readiness is not green yet (exit $rc)." >&2
  echo "Check: journalctl -u $SERVICE_NAME -n 200 --no-pager" >&2
  exit "$rc"
fi
