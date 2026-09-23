# ToS_Companion Replay API

## Purpose

This API exists so Codex or other local tooling can inspect recorded sessions and deterministic replay state directly, without scraping or controlling the browser UI.

Base service on joelab:

    http://tos-companion:8787

When accessed through the browser-facing host/reverse proxy, use that host with the same /api paths.

## Recommended machine workflow

1. List available recorded sessions.
2. Pick a session and symbol.
3. Use the stateless inspect endpoint at an exact replay timestamp or cursor.
4. Read the returned machine state:
   - quote
   - completed 10-second bars
   - AE snapshot
   - pattern observations
   - replay cursor/timestamp/progress

For automated strategy research, prefer POST /api/replay/inspect over the interactive replay endpoints because inspect uses an isolated ReplayEngine and does not mutate the UI replay state.

---

## GET /api/replay/sessions

Lists recorded sessions available under the configured recordings root.

Request:

    GET /api/replay/sessions

Example response:

    [
      {
        "session_id": "2026-09-23_070000_session",
        "started_at_et": "2026-09-23T07:00:00-04:00",
        "ended_at_et": "2026-09-23T15:00:00-04:00",
        "symbols": ["TOPS", "BENF", "IMCC"],
        "counts": {
          "TOPS": {"LEVELONE_EQUITIES": 12345}
        },
        "stop_reason": "3pm_cutoff"
      }
    ]

Use session_id exactly as returned.

---

## POST /api/replay/inspect

Preferred endpoint for Codex and batch tooling.

Creates a new isolated ReplayEngine for the request, loads one recorded ticker, rebuilds deterministically to the requested point, returns the full replay/session snapshot, then discards the isolated engine.

This endpoint does not alter:
- live Schwab subscriptions
- live CompanionSession
- recorder state
- browser replay position
- another inspect request

### Inspect by cursor

Request:

    POST /api/replay/inspect
    Content-Type: application/json

    {
      "session_id": "2026-09-23_070000_session",
      "symbol": "TOPS",
      "cursor": 12500
    }

### Inspect by timestamp

Request:

    POST /api/replay/inspect
    Content-Type: application/json

    {
      "session_id": "2026-09-23_070000_session",
      "symbol": "TOPS",
      "timestamp_ms": 1790165800000
    }

Timestamp behavior:

The engine rebuilds through the last recorded event whose stream timestamp is less than or equal to timestamp_ms.

If both timestamp_ms and cursor are supplied, timestamp_ms takes precedence.

### Response shape

    {
      "replay": {
        "status": "PAUSED",
        "session_id": "2026-09-23_070000_session",
        "symbol": "TOPS",
        "cursor": 12500,
        "total_events": 48000,
        "current_ts_ms": 1790165800000,
        "progress": 0.2604,
        "speed": 1
      },
      "session": {
        "connection_state": "DISCONNECTED",
        "active_symbol": "TOPS",
        "watched_symbols": ["TOPS"],
        "recorder_state": {
          "active": false
        },
        "symbols": {
          "TOPS": {
            "symbol": "TOPS",
            "quote": {
              "ts_ms": 1790165800000,
              "bid": 0.71,
              "ask": 0.72,
              "last": 0.715,
              "bid_size": 100,
              "ask_size": 200,
              "volume": 123456,
              "source_ts_type": "QUOTE_TS",
              "raw_source": "SCHWAB_STREAM"
            },
            "history_bars": [],
            "bars_10s": [
              {
                "ts": 1790165790,
                "open": 0.70,
                "high": 0.72,
                "low": 0.70,
                "close": 0.715,
                "volume": 1200,
                "is_extended": true,
                "stale": false
              }
            ],
            "ae_snapshot": {},
            "llm_output": null,
            "trade_state": null,
            "pattern_observations": []
          }
        }
      }
    }

Important fields for strategy research:

- replay.current_ts_ms
  - authoritative historical replay clock
- replay.cursor
  - deterministic event position
- session.symbols[SYMBOL].quote
  - reconstructed L1 state at that point
- session.symbols[SYMBOL].bars_10s
  - all completed 10-second bars available up to that point
- session.symbols[SYMBOL].ae_snapshot
  - Analysis Engine state known at that point
- session.symbols[SYMBOL].pattern_observations
  - pattern detections known at that point

---

## Interactive Replay API

These endpoints control the single Replay instance used by the browser Replay tab.

They are useful for manual playback but are not preferred for parallel/batch Codex analysis.

### GET /api/replay/state

Returns the current interactive Replay instance.

    GET /api/replay/state

### POST /api/replay/load

    {
      "session_id": "2026-09-23_070000_session",
      "symbol": "TOPS"
    }

Loads the symbol into the interactive replay instance at cursor 0.

### POST /api/replay/play

Supported speeds:

    1
    5
    20
    "MAX"

Example:

    {
      "speed": 20
    }

### POST /api/replay/pause

No request body.

### POST /api/replay/step

    {
      "count": 1
    }

Advances the requested number of raw recorded events.

### POST /api/replay/seek

    {
      "cursor": 12500
    }

Seeking rebuilds replay state from the beginning to the requested cursor. It does not reverse-mutate indicators.

---

## Live state API

Codex can also inspect the currently running live Companion session without using the browser.

### GET /api/state

Returns the live session snapshot:

    GET /api/state

Includes:
- connection_state
- active_symbol
- watched_symbols
- recorder_state
- per-symbol quote
- per-symbol freshness
- history bars
- live 10-second bars
- AE snapshot
- pattern observations

This is live state, not historical replay state.

### GET /api/health

Small live health summary.

### GET /api/readiness

Service/auth/LLM/runtime readiness without exposing Schwab tokens.

---

## curl examples from joelab

List recordings:

    curl -sS http://tos-companion:8787/api/replay/sessions | jq

Inspect TOPS at an exact historical timestamp:

    curl -sS -X POST http://tos-companion:8787/api/replay/inspect \
      -H 'Content-Type: application/json' \
      -d '{
        "session_id":"2026-09-23_070000_session",
        "symbol":"TOPS",
        "timestamp_ms":1790165800000
      }' | jq

Inspect at a cursor:

    curl -sS -X POST http://tos-companion:8787/api/replay/inspect \
      -H 'Content-Type: application/json' \
      -d '{
        "session_id":"2026-09-23_070000_session",
        "symbol":"TOPS",
        "cursor":12500
      }' | jq

Read live state:

    curl -sS http://tos-companion:8787/api/state | jq

If running the curl command from the joelab host rather than a container attached to joelab-ingress, use the deployed host/reverse-proxy address instead of the Docker service name if tos-companion is not resolvable from the host namespace.

---

## Strategy-testing contract

For a manually identified real setup, record at minimum:

- session_id
- symbol
- approximate setup timestamp
- optional exact cursor once resolved
- setup label/type
- human notes

Then use POST /api/replay/inspect at that timestamp to ask:

"What did ToS_Companion know at this exact historical point?"

Do not inspect a later timestamp and attribute that state to an earlier decision point.

The raw recording remains immutable. Human labels and later outcome measurements should reference the recording by session_id + symbol + timestamp/cursor rather than modifying the JSONL source files.

---

## Known evidence limitations

Current recordings are primarily LEVELONE_EQUITIES L1 data.

Replay can accurately reconstruct the evidence captured, but it should not imply true trade-by-trade fill precision without time-and-sales evidence.

Some older recordings may also lack the exact higher-timeframe/profile context that live AE fetched at symbol enrollment. In those cases replay must remain partial rather than fetching current/future Schwab data and contaminating the historical run.

See also:

    docs/replay_evaluation_architecture.md
