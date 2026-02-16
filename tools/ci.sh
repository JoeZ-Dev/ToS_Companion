#!/usr/bin/env bash
set -euo pipefail

# CI helper: run unit tests and (optional) packaging smoke on Linux.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Running pytest..."
pytest -q

echo "To run Windows smoke, execute tools/windows_smoke.ps1 on a Windows runner with PyInstaller available."
