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

