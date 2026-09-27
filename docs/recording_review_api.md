# Recording Review API

This component exists so a ChatGPT/Codex session can review recorded momentum sessions without scraping the browser and without modifying immutable market evidence.

## Goals

- expose recorded sessions in deterministic, compact windows
- make broad setup discovery possible across many recordings
- support a second verification pass that cannot see price action after the proposed trigger
- store model/human annotations separately from raw recordings
- keep setup labels machine-readable for later detector comparison and MAE/MFE analysis

## Endpoints

### GET /api/review/recordings

Returns the recording corpus and symbols available for review.

### POST /api/review/window

Request:

    {
      "session_id": "2026-09-23_070000_session",
      "symbol": "TOPS",
      "start_ms": 1790161200000,
      "end_ms": 1790162400000
    }

Windows are limited to 45 minutes so the returned packet remains bounded and the replay session's 10-second bar retention cannot silently truncate the requested evidence.

The response contains:

- 10-second bars in the requested window
- VWAP points in the requested window
- reconstructed quote at the end of the window
- AE snapshot at the end of the window
- current pattern-engine observations at the end of the window
- market context when present
- replay/data-quality metadata
- an explicit `future_data_included: false` marker

This endpoint is for discovery. A reviewer can move sequentially through a recording and identify candidate momentum setups, including valid setups that later failed.

### POST /api/review/verify

Request:

    {
      "session_id": "2026-09-23_070000_session",
      "symbol": "TOPS",
      "trigger_ms": 1790161800000,
      "lookback_ms": 600000
    }

The packet ends at `trigger_ms`. No event after the proposed trigger is replayed into the response.

Use this for the second-pass question:

> Did this setup genuinely exist using only information that was available at the proposed trigger?

This is the primary hindsight-bias guard.

### POST /api/review/annotations

Example:

    {
      "session_id": "2026-09-23_070000_session",
      "symbol": "TOPS",
      "setup_type": "ascending_triangle",
      "setup_start_ms": 1790161700000,
      "trigger_ms": 1790161800000,
      "valid_at_time": true,
      "outcome": "failed",
      "confidence": 0.86,
      "evidence": {
        "resistance": 4.52,
        "resistance_touches": 4,
        "higher_lows": true
      },
      "invalidation": "lost rising support after breakout attempt",
      "notes": "Legitimate setup despite later failure",
      "review_pass": "discovery",
      "source": "chatgpt"
    }

Annotations are append-only JSONL under:

    ~/.tos_companion/review_annotations/annotations.jsonl

They are deliberately outside the recording directories.

### GET /api/review/annotations

Optional query parameters:

- `session_id`
- `symbol`

## Recommended ChatGPT workflow

### Pass 1: Discovery

Review each ticker sequentially in 15-20 minute windows.

The reviewer should identify any credible momentum setup visible in real time, not only patterns already implemented in ToS_Companion. Examples can include ascending triangles, micro pullbacks, flags, high-of-day breaks, VWAP reclaims, breakout/retests, round-number reclaims, failed breakouts, and other recurring structures.

A setup that later fails should still be labeled valid when the evidence at the trigger justified the setup.

Do not use later outcome to decide whether the setup was valid at the trigger.

### Pass 2: Blind verification

For every proposed setup, call `/api/review/verify` ending at its trigger timestamp.

Judge only whether the structure existed at that moment.

Save the verification result as another annotation using `review_pass: "verification"` or retain the original discovery annotation and add a verification-specific note/evidence packet in downstream tooling.

## Annotation semantics

Recommended outcome values:

- `succeeded`
- `failed`
- `no_follow_through`
- `invalid_before_trigger`
- `unknown`

`valid_at_time` answers a different question from `outcome`.

A setup can be:

    valid_at_time = true
    outcome = failed

Those examples are important detector positives. The pattern engine should generally be capable of finding a legitimate setup even when the trade later fails.

## Non-goals

This API does not:

- ask an LLM to trade
- alter pattern thresholds
- automatically promote model labels to ground truth
- rewrite raw recordings
- infer fills or profitability
- include future data in verification packets

Later evaluation code can compare these annotations with detector observations and compute MAE/MFE and expectancy metrics.
