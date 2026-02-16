# Analysis Engine — Historical Market Analysis (AE-1.0)

## 0. Purpose

Ingest multi-timeframe historical OHLCV for a single equity symbol and produce a **compressed, deterministic market profile** used by the LLM coach and UI.

- Runs **once per symbol** (not realtime)
- Deterministic (no AI)
- Produces **one JSON market profile** per run

## 0.1 Scope Split (Clarification — Spec Factory tightening)

This document defines two deterministic outputs:

1) **Historical Market Profile (AE-1.0)**: computed on symbol load (or on demand), stored in SQLite `market_profile.profile_json`.
2) **Live Analysis Snapshot (AE-1.1, MVP)**: computed repeatedly during runtime from live/near-live market data and used to gate downstream features (LLM Coach, overlays). The Live Snapshot is **not AI** and produces deterministic fields only.

The Analysis Engine **MUST NOT** produce strategy suggestions (entry/exit/stop). That responsibility belongs exclusively to the LLM Coach.

---

## 1. Required Inputs (Strict)

### 1.1 Timeframes & Coverage

The engine MUST ingest the following datasets:

| Timeframe | Coverage                                  |
| --------- | ----------------------------------------- |
| 4-hour    | 6 months                                  |
| 1-hour    | 1 week                                    |
| 5-minute  | 2 days                                    |
| 1-minute  | current session (includes extended hours) |

### 1.1.1 Session Definitions (ET)

- **RTH (regular trading hours):** 09:30–16:00 ET
- **Extended session window (for “current session” datasets):** 04:00–20:00 ET for the current ET trading day
- “Current session” for required 1-minute data means the **extended session window** above (includes premarket + afterhours for that ET day).
- All timestamps remain UTC in storage and transport; ET is used only to define session boundaries.
- **VWAP anchoring rule (for AE-1.1 + UI studies):** VWAP starts at **04:00 ET** and accumulates continuously through **20:00 ET** (no reset at 09:30 ET).

### 1.2 DataFrame Schema

Each timeframe input is a pandas DataFrame with **exact columns**:

- `ts_utc` (str, UTC ISO-8601, e.g., `2026-02-07T14:31:20Z`)
- `open` (float)
- `high` (float)
- `low` (float)
- `close` (float)
- `volume` (float)
- `is_extended` (int, 0/1)

Constraints:

- `ts_utc` MUST be monotonic increasing
- No duplicate `ts_utc` within a timeframe

---

## 2. Output (Strict)

### 2.1 Output Contract

The engine outputs exactly one JSON object per run and stores it in SQLite `market_profile.profile_json`.

### 2.2 Final JSON Schema (Required)

```json
{
  "symbol": "AAPL",
  "created_at_utc": "2026-02-07T11:00:00Z",
  "trend": {
    "bias_6m": "bullish",
    "bias_1w": "neutral",
    "ema20_slope_4h": 0.0123,
    "ema20_slope_1h": -0.0031
  },
  "volatility": {
    "atr14_4h": 0.42,
    "atr14_percentile_6m": 82,
    "regime": "expanding"
  },
  "levels": {
    "resistance_zones": [
      {"price": 19.85, "band": 0.03, "touches": 4, "tf_weight": 3, "recency_score": 0.71}
    ],
    "support_zones": [
      {"price": 18.92, "band": 0.03, "touches": 5, "tf_weight": 3, "recency_score": 0.88}
    ]
  },
  "behavior": {
    "avg_pullback_pct": 1.6,
    "median_pullback_pct": 1.2,
    "spike_failure_rate": 0.42,
    "avg_vwap_extension_pct_1m": 0.9
  },
  "notes": {
    "method_version": "AE-1.0"
  }
}
```

### 2.3 Fixed Cardinalities

- Output exactly:
  - `resistance_zones`: **top 10**
  - `support_zones`: **top 10**

## 2.4 Live Analysis Snapshot Output Contract (AE-1.1, MVP) *(Clarification — Spec Factory tightening)*

### 2.4.1 Purpose
Emit a deterministic snapshot for the active symbol used by UI overlays and as the **only** allowed numeric input source for the LLM Coach.

### 2.4.2 Top-Level Schema (Required)
- `symbol` (str)
- `as_of_ts_ms` (int, UTC epoch milliseconds)
- `market_state` (`premarket|normal|afterhours`)
- `status` (`ok|error`)
- `data_quality` (`ok|partial|stale|no_data|error`)
**Note (integration boundary):**
AE-1.1 does NOT emit the following LLM-payload fields required by `specs.md §11.2.5`: `schema_version`, `session_mode`, and the `quote{bid,ask,last,volume}` object. These fields are deterministically added by the application during normalization per `specs.md §11.2.5`.

NOTE (MVP — Final): AE-1.1 output defined in this document is NOT the final LLM input payload shape. The application constructs the LLM payload per `specs.md §11.2.5` by appending `schema_version`, `session_mode`, `quote{bid,ask,last,volume}`, and mapping `bars_window_5m` → `bars_window`. The LLM payload field names MUST match `specs.md §11.2.5` exactly.


If `data_quality != ok`:
- `status` MAY remain `ok` if the snapshot is structurally valid.
- Computed fields SHOULD remain populated when deterministically computable.
- `status` MUST be `error` only when the snapshot cannot be generated due to an internal exception or contract violation.
- Downstream components (LLM Coach, overlays) MUST NOT run unless `status=ok` AND `data_quality=ok`.


### 2.4.3 Allowed Raw Bars (LLM Contract Alignment)
- The snapshot MAY include multiple internal timeframes for calculation.
- The snapshot MUST expose **raw bars** only as:
  - `bars_window_5m`: capped OHLCV window

No 1m/10s/tick bars may be exposed as raw bar arrays.

### 2.4.3.1 AE-1.1 Invocation & Window Defaults *(MVP — Intent Lock)*

**Recompute cadence:**
- Recompute the Live Analysis Snapshot on each **completed 10s bar close** while the streaming connection is `CONNECTED`.
- If streaming is `RECONNECTING` or `STALE`, recompute is permitted but `data_quality` MUST reflect degradation.

**bars_window_5m:**
- Expose exactly `bars_window_5m` with a maximum of **120 bars**, ordered **chronologically ascending** (oldest → newest).
- Minimum required for `data_quality=ok`: **>= 10** completed 5m bars.

**Event lookbacks (internal use; not exposed as raw bars):**
- Event detection MAY use 1m and 10s internally, but must summarize into event objects only.
- Default internal lookback for events: last **120 minutes** of 1m data.

**Cardinality caps (to prevent unbounded payload growth):**
- `rejection_events`: max **10**
- `volume_spike_events`: max **10**
- `largest_red_candle_events`: max **3**
- `largest_green_candle_events`: max **3**
- `max_adverse_excursion`: single object
- `max_favorable_excursion`: single object

**data_quality thresholds (MVP):**
- `ok`: quote age <= **5s** AND bars_window_5m has >= 10 completed bars
- `stale`: quote age > **5s** but <= **60s**
- `no_data`: quote age > **60s** OR no streaming updates received in >60s
- `partial`: quotes fresh but bars_window_5m has < 10 completed bars
- `error`: internal exception or contract violation

### 2.4.4 Deterministic Structures
- `vwap`:
  - **VWAP anchoring rule (for AE-1.1 + UI studies):** VWAP starts at **04:00 ET** and accumulates continuously through **20:00 ET** (no reset at 09:30 ET).

  - `vwap_bands` (object | null): deterministic band levels derived from `vwap_price`; null when `vwap_price` is null.
- `levels`:
  - support/resistance zones and metadata (strength, timeframe origin)
- `events` (anti-information-loss layer):
  - `rejection_events`
  - `largest_red_candle_events`
  - `largest_green_candle_events`
  - `volume_spike_events`
  - `max_adverse_excursion`
  - `max_favorable_excursion`
Each event MUST include at minimum: `timestamp_ms` (int, UTC epoch milliseconds), `move_pct_from_level` (if level-related), `time_to_move_seconds`, and `volume_multiple`.

- `signals` (qualitative flags):
  - breakout / pullback / continuation / failure flags
  - qualitative confidence: `low|medium|high` (no opaque numeric scores)

**levels schema (MVP — Final):**
- `levels`: array of objects, each:
  - `price` (float)
  - `kind` (str)  # e.g., "support", "resistance", "vwap_related" (AE-defined vocabulary)
  - `tf_origin` (enum: `4h|1h|5m`)
  - `strength` (enum: `low|medium|high`)
  - `label` (str | null)

**events schema (MVP — Final):**
- `events`: object with keys:
  - `rejection_events`: array[event]
  - `largest_red_candle_events`: array[event]
  - `largest_green_candle_events`: array[event]
  - `volume_spike_events`: array[event]
  - `max_adverse_excursion`: event | null
  - `max_favorable_excursion`: event | null
- `event` object required fields:
  - `timestamp_ms` (int, UTC epoch ms)
  - `time_to_move_seconds` (float | int)
  - `volume_multiple` (float | int | null)
  - `move_pct_from_level` (float | null)

**signals schema (MVP — Final):**
- `signals`: array of objects, each:
  - `type` (enum: `breakout|pullback|continuation|failure`)
  - `confidence` (enum: `low|medium|high`)
  - `timestamp_ms` (int, UTC epoch ms)

### 2.4.4.1 Event & Signal Algorithms (MVP — Final)

All event/signal computations are deterministic and computed on 1-minute bars using the last 120 minutes of 1m data (per §2.4.3.1).

Constants (MVP — Final):
- `LEVEL_TOUCH_TOL_PCT = 0.10`  (0.10% proximity to a level price)
- `REJECTION_REVERSAL_PCT = 0.30` (0.30% reversal from touch extreme)
- `REJECTION_MAX_SECONDS = 180` (must reverse within 180s)
- `VOL_SPIKE_MULT = 3.0`
- `VOL_BASELINE_BARS = 30` (median of last 30 completed 1m volumes)
- `BREAKOUT_MARGIN_PCT = 0.05` (0.05% above level)
- `BREAKOUT_CONFIRM_BARS = 2` (two consecutive 1m closes)
- `FAILURE_WINDOW_BARS = 10`

Volume multiple:
- For any event with `volume_multiple`, compute:
  - `baseline = median(volume of last VOL_BASELINE_BARS completed 1m bars prior to event bar)`
  - `volume_multiple = event_bar_volume / baseline` (if baseline==0 → set to null)

largest_red_candle_events / largest_green_candle_events:
- Use 1m bars in lookback.
- Candle body = `abs(close - open)`.
- Red = close < open; Green = close > open.
- Select top N by body size (N caps already defined in §2.4.3.1).
- timestamp_ms = event bar close timestamp.

volume_spike_events:
- Event occurs on a 1m bar if `volume_multiple >= VOL_SPIKE_MULT`.
- timestamp_ms = event bar close timestamp.
- move_pct_from_level = null (not level-related by default).
- time_to_move_seconds = 0.

rejection_events:
- For each level price `L` in `levels`:
  - A “touch” occurs when bar high/low enters `L ± (L*LEVEL_TOUCH_TOL_PCT/100)`.
  - After touch, a rejection occurs if within REJECTION_MAX_SECONDS:
    - For resistance touch (price at/above L): price moves downward by >= REJECTION_REVERSAL_PCT from the max reached during the touch window.
    - For support touch (price at/below L): price moves upward by >= REJECTION_REVERSAL_PCT from the min reached during the touch window.
- timestamp_ms = timestamp of the bar where the reversal threshold is first met.
- move_pct_from_level = `(close_at_reversal - L) / L * 100`.
- time_to_move_seconds = seconds from first touch bar timestamp to reversal timestamp.
- volume_multiple computed on the reversal bar.

signals (breakout/pullback/continuation/failure):
- Define `prior_high` as the max 1m high over the lookback excluding the most recent bar.
- breakout = last `BREAKOUT_CONFIRM_BARS` 1m closes each > `prior_high * (1 + BREAKOUT_MARGIN_PCT/100)`.
- failure = breakout attempt where within `FAILURE_WINDOW_BARS` after first close-above, a 1m close returns <= `prior_high`.
- pullback = after breakout, a drawdown from the local max close of >= 0.30% within 20 bars.
- continuation = after pullback, a higher high close than the breakout max close within 10 bars.
Confidence:
- `high` if breakout is true AND volume_multiple on the breakout bar is >= 2.0
- else `medium` if breakout is true
- else `low`

### 2.4.5 Explicit Non-Responsibilities
The Analysis Engine MUST NOT:
- generate entry/exit/stop values
- output discretionary “risk opinions”
- reinterpret its own signals based on context
- select among strategies (single-strategy MVP)

---

## 3. Algorithms (Final Constants)

### 3.1 Indicators

- EMA20 for 4h and 1h trend bias
- ATR14 for volatility regime

### 3.2 Swing Detection (Zone Candidates)

Define a swing high at index `i` if:

- `high[i]` is the maximum of `high[i-lookback : i+lookback]`

Define a swing low at index `i` if:

- `low[i]` is the minimum of `low[i-lookback : i+lookback]`

Lookbacks:

- 4h: `lookback = 3`
- 1h: `lookback = 3`
- 5m: `lookback = 5`

(1m is not used for zone discovery in AE-1.0.)

### 3.3 Zone Clustering

Cluster swing prices into zones using a fixed percent band:

- `cluster_band_pct = 0.15%` of price

For a zone centered at `price`, its band is:

- `band_$ = price * 0.0015`

Swings within `± band_$` are assigned to the same zone.

### 3.4 Timeframe Weighting

Each swing contributes a timeframe weight:

- 4h: `tf_weight = 3`
- 1h: `tf_weight = 2`
- 5m: `tf_weight = 1`

### 3.5 Recency Score

Recency score is computed from swing age (in bars) as:

- `recency_score = exp(-age_bars / half_life)`

Half-lives:

- 4h: `half_life = 40`
- 1h: `half_life = 60`
- 5m: `half_life = 100`

### 3.6 Zone Touch Count

A "touch" occurs when any bar’s `high/low` range intersects the zone band.

### 3.7 Zone Ranking

Compute zone score:

- `score = touches * tf_weight * (0.5 + 0.5 * recency_score)`

Select top 10 by score for resistance and support separately.

---

## 4. Trend Bias (Final)

### 4.1 EMA20 Slope

Compute EMA20 on close.

EMA20 slope is measured as:

- `ema20_slope = (ema20_last - ema20_prev_k) / k`

Where:

- 4h: `k = 10` bars
- 1h: `k = 20` bars

### 4.2 Bias Label

- `bullish` if `ema20_slope > +0.0`
- `bearish` if `ema20_slope < -0.0`
- `neutral` if `abs(ema20_slope) < 1e-6`

---

## 5. Volatility Regime (Final)

### 5.1 ATR14

Compute ATR(14) on 4h bars.

### 5.2 ATR Percentile

Compute ATR14 percentile vs the prior 6 months of 4h ATR14 values:

- `atr14_percentile_6m` in [0, 100]

### 5.3 Regime Label

Compute ATR slope over last 10 ATR points:

- `atr_slope = (atr_last - atr_prev_10) / 10`

- `expanding` if `atr_slope > 0`

- `contracting` if `atr_slope < 0`

- `flat` if `abs(atr_slope) < 1e-6`

---

## 6. Behavioral Metrics (Final)

All behavior metrics are computed on the **1-minute** timeframe using the current session only.

### 6.1 Pullback %

Define an impulse as any move where close-to-close gain over 5 bars is ≥ 1.0%. For each impulse:

- Peak = close at end of impulse
- Trough = minimum close within the next 20 bars
- Pullback% = `(peak - trough) / peak * 100`

Outputs:

- `avg_pullback_pct`
- `median_pullback_pct`

### 6.2 Spike Failure Rate

Define an attempt as:

- close exceeds the current-session prior high (computed from earlier 1m bars)

Failure if:

- within next 10 bars, close returns below that prior-high level

Rate:

- failures / attempts (0..1)

### 6.3 VWAP Extension %

Compute session VWAP on 1m bars. For each bar:

- extension% = `abs(close - vwap) / vwap * 100`

Output:

- `avg_vwap_extension_pct_1m` (mean over session)

---

## 7. Explicit Non-Responsibilities

The Analysis Engine does NOT:

- Generate trade signals
- Predict direction
- Make execution decisions
- Run continuously during the session

---

## 8. Versioning

- `notes.method_version` is fixed to `AE-1.0` for MVP.
- Any algorithm change increments this version.
