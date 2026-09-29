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

If a requested window falls wholly before the first recorded event, the API returns an empty evidence packet instead of clamping forward into future data. The packet reports:

- `window.availability.status = "before_recording"`
- the first/last recorded event timestamps
- `events_in_window = 0`

Likewise, a wholly post-recording request is reported as `after_recording`. These are data-availability states, not 45-minute-window errors.

Each packet also includes a `review_context` object derived from the packet end timestamp. During the regular-session open it reports:

- 09:30:00-09:34:59 ET: `opening_volatility_context = "very_high"`
- 09:35:00-09:44:59 ET: `opening_volatility_context = "elevated"`
- otherwise: `opening_volatility_context = "normal"`

This is review context only. It does not alter detector behavior or automatically invalidate a setup.

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

### POST /api/review/l1-window

Returns reconstructed carried-forward Level 1 quote state for a tightly bounded
historical interval. This is intended for execution-confirmation research around
a candidate trigger, not for bulk whole-session transfer.

Request:

    {
      "session_id": "2026-09-23_070000_session",
      "symbol": "TOPS",
      "start_ms": 1790161790000,
      "end_ms": 1790161810000
    }

The interval may not exceed 120 seconds.

The response contains one frame per recorded L1 event in the requested interval.
Each frame contains the quote state known immediately after that event:

- timestamp_ms
- bid / ask / last
- bid_size / ask_size / last_size when captured
- cumulative volume
- spread
- source timestamp type / raw source when available

Because Schwab L1 messages are deltas, the endpoint first reconstructs state
through the event immediately before the requested window. Fields such as bid
and ask therefore carry forward correctly when an in-window event updates only
last price or volume.

The endpoint is read-only, does not alter the browser replay, and includes
future_data_included: false. Callers choose the requested end timestamp; WAMO
should keep pre-trigger setup evidence separate from explicitly post-trigger
execution-response horizons.

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

### Opening-session review rule

The regular-session open requires stricter structural evidence because 09:30-09:35 ET can contain abrupt price discovery, wide swings, false breaks, and fast reversals that resemble patterns on coarser bars.

From 09:30-09:35 ET:

- do not label ordinary opening expansion, a single sharp push, a single reversal, or a one-shot reclaim as a structured setup by itself
- require structure that persists across multiple short-interval observations
- prefer repeated interaction with a defined level, compression, a controlled pullback, retest/reclaim behavior, or a clear higher-low/lower-high sequence
- valid opening setups are allowed; the time window is not an automatic rejection rule

From 09:35-09:45 ET, opening volatility is still considered elevated. Normal pattern interpretation is allowed, but the reviewer should keep a higher bar for structure than later in the session.

After 09:45 ET, use normal review standards unless the recording itself shows an unusually unstable regime.

The replay/L1-derived packet remains the machine-review source of truth. Human tick-chart screenshots may be used for adjudicating ambiguous examples, but should not replace the timestamp-bounded replay evidence.

### Pass 2: Blind verification

For every proposed setup, call `/api/review/verify` ending at its trigger timestamp.

Judge only whether the structure existed at that moment.

Save the verification result as another annotation using `review_pass: "verification"` or retain the original discovery annotation and add a verification-specific note/evidence packet in downstream tooling.

### Outcome consistency

Outcome is evaluated only after `valid_at_time` has been decided from trigger-bounded evidence.

For corpus labeling, use a consistent 15-minute post-trigger observation horizon when the recording contains that much data. This horizon is an evaluation convention, not a trading rule or target.

Within that horizon:

- `succeeded`: clear favorable continuation from the trigger before structural invalidation
- `failed`: a valid setup triggers and then reaches its structural invalidation before meaningful follow-through
- `no_follow_through`: the setup remains valid but produces neither clear continuation nor structural failure within the horizon
- `invalid_before_trigger`: blind verification shows that the proposed setup was not actually valid at the trigger
- `unknown`: insufficient post-trigger evidence, including recordings that end too soon

When possible, record the evaluation horizon and the observed MFE/MAE separately from the qualitative outcome. Do not change the validity label based on later price action.

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
