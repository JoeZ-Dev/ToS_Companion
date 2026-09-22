#!/usr/bin/env bash
set -euo pipefail

SYMBOLS_CSV="${1:-}"
RECORD_SECONDS="${RECORD_SECONDS:-30}"
BASE_URL="${BASE_URL:-http://tos-companion:8787}"

if [[ -z "$SYMBOLS_CSV" ]]; then
  echo "Usage: $0 SYMBOL[,SYMBOL...]"
  echo "Example: RECORD_SECONDS=60 $0 IMCC,LHSW"
  exit 2
fi

if ! docker inspect tos-companion >/dev/null 2>&1; then
  echo "ERROR: tos-companion container is not running." >&2
  exit 3
fi

payload="$(
  python3 - "$SYMBOLS_CSV" <<'PY'
import json, sys
symbols = [s.strip().upper() for s in sys.argv[1].split(",") if s.strip()]
print(json.dumps({"symbols": symbols}, separators=(",", ":")))
PY
)"

echo "Starting recorder for $SYMBOLS_CSV..."
start_json="$(
  docker run --rm --network joelab-ingress curlimages/curl:latest     --fail --silent --show-error     -H 'Content-Type: application/json'     -d "$payload"     "$BASE_URL/api/recording/start"
)"
echo "$start_json" | python3 -m json.tool

session_dir="$(
  python3 -c 'import json,sys; print(json.load(sys.stdin)["session_dir"])' <<<"$start_json"
)"

echo
echo "Recorder request completed. No browser connection is required."
echo "Waiting ${RECORD_SECONDS}s while the server records..."
sleep "$RECORD_SECONDS"

echo
echo "Checking recorder is still active..."
state_json="$(
  docker run --rm --network joelab-ingress curlimages/curl:latest     --fail --silent --show-error "$BASE_URL/api/state"
)"
python3 - <<'PY' <<<"$state_json"
import json, sys
state = json.load(sys.stdin)
rec = state.get("recorder_state") or {}
if not rec.get("active"):
    raise SystemExit("ERROR: recorder stopped before explicit stop")
print("active:", rec.get("active"))
print("symbols:", ",".join(rec.get("symbols") or []))
print("session_dir:", rec.get("session_dir"))
PY

echo
echo "Stopping recorder..."
stop_json="$(
  docker run --rm --network joelab-ingress curlimages/curl:latest     --fail --silent --show-error     -X POST "$BASE_URL/api/recording/stop"
)"
echo "$stop_json" | python3 -m json.tool

echo
echo "Validating recording files..."
docker exec -i tos-companion python - "$session_dir" "$SYMBOLS_CSV" <<'PY'
import json
from pathlib import Path
import sys

session_dir = Path(sys.argv[1])
symbols = [s.strip().upper() for s in sys.argv[2].split(",") if s.strip()]
manifest_path = session_dir / "manifest.json"
if not manifest_path.exists():
    raise SystemExit(f"ERROR: missing manifest: {manifest_path}")

manifest = json.loads(manifest_path.read_text())
print("manifest:", manifest_path)
print("stop_reason:", manifest.get("stop_reason"))
print("services:", manifest.get("services"))

if manifest.get("stop_reason") != "browser_stop":
    raise SystemExit(f"ERROR: unexpected stop reason: {manifest.get('stop_reason')!r}")

total = 0
for symbol in symbols:
    path = session_dir / f"{symbol}.jsonl"
    manifest_count = (
        manifest.get("counts", {})
        .get(symbol, {})
        .get("LEVELONE_EQUITIES", 0)
    )
    line_count = 0
    if path.exists():
        with path.open() as fh:
            line_count = sum(1 for line in fh if line.strip())
    print(f"{symbol}: jsonl_lines={line_count} manifest_count={manifest_count}")
    if line_count != manifest_count:
        raise SystemExit(
            f"ERROR: {symbol} JSONL/manifest count mismatch "
            f"({line_count} != {manifest_count})"
        )
    total += line_count

if total == 0:
    raise SystemExit(
        "ERROR: recorder produced zero LEVELONE_EQUITIES events; "
        "choose symbols with active quote updates and retry"
    )

print(f"PASS: {total} raw L1 events persisted with no browser connection.")
PY
