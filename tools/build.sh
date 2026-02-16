#!/usr/bin/env bash
set -euo pipefail
# Windows EXE packaging per specs §2.2 (PyInstaller).
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
pyinstaller --clean --noconfirm --onefile --name momentum_companion src/momentum_companion/ui/__main__.py
