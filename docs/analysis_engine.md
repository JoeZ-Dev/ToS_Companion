# Analysis Engine (Momentum Context) – AE-1.x

## Purpose

Provide a deterministic market context for a single symbol to support a momentum day-trading workflow (including premarket). The engine:
- Gathers deterministic state (no AI, no probabilistic scoring).
- Extracts multi-timeframe structural levels.
- Computes binary “go/no-go” boxes and numeric context only.
- Separates facts (AE) from interpretation (LLM/UX).

No trade recommendations, entries, exits, or stop levels are produced.

## Scope

AE responsibilities:
1. Gather deterministic state.
2. Extract structural levels across timeframes.
3. Compute binary boxes and key distances.
4. Expose context for LLM/UI.
5. Never generate trade advice.

Out of scope / deferred:
- Float turnover percentage.
- Minute-of-day multi-session RVOL baseline.
- Consolidation_break_events taxonomy (keep compression simple).
- Long-term storage of multi-day 1m histories beyond what is needed to initialize.

## Inputs

- **Higher timeframe** (on symbol load):
  - Preferred: 180 days of 4h bars (fallback: 1 year of daily bars).
  - Prior 3 daily candles.
  - Prior close.
  - Current session open.
- **Intraday (current session)**:
  - 1m bars built from our 10s aggregator (04:00–20:00 ET).
  - VWAP anchored 04:00–20:00 ET.
  - Market proxy (SPY or QQQ) last price/percent change.
- **Schema per bar**: ts_utc (ISO), open, high, low, close, volume, is_extended (0/1), monotonic timestamps.

## Structural Extraction (Higher Timeframe)

On symbol load:
- Compute EMA9 on 4h (or daily fallback) to derive `is_above_4h_ema`.
- Detect swing highs/lows with a fixed fractal lookback (e.g., 3 bars).
- Cluster swing highs into resistance zones using a fixed band (e.g., 1.5% of price).
- Score clusters by:
  - `touch_count`
  - `recency_weight` (decay on bar age)
  - `duration_at_level` (time price spent inside band)
- Output top **3** resistance clusters and top **3** support clusters (swing lows):
  - `price_zone_low`, `price_zone_high`
  - `strength_score`
  - `timeframe_source` (4h or daily fallback)
- Discard raw higher-timeframe bars after extraction; keep clusters and EMA state.

## Intraday Deterministic Boxes (per completed 1m bar)

- `is_above_open` (RTH only; NA premarket)
- `is_above_vwap` (VWAP anchored 04:00–20:00 ET)
- `intraday_range_pct` = (session_high - session_low) / session_open * 100
- `is_volatile_enough` = `intraday_range_pct` > fixed threshold (constant)
- `macd_regime` on 1m closes: `bullish|bearish|neutral` (standard 12/26/9 MACD)
- `is_above_4h_ema` (from structural extract)
- `is_market_green` (SPY % change > 0)
- `is_above_open` (RTH only) computed from REST RTH open (09:30 ET). If RTH open missing: null.
- Micro intraday context (uses completed 1m bars only):
  - 15m swing highs/lows (micro resistance/support) = max high/min low over last 15 completed 1m bars (null if <15 bars).
  - 5m and 15m ranges in % of last price: `(maxHigh - minLow) / last_price * 100` over last 5/15 completed 1m bars (null if insufficient bars or last_price missing).
  - Compression ratio = range_5m_pct / range_15m_pct (if both present and 15m range > 0).
  - Micro state: `COIL` if compression_ratio <= 0.35; `EXPAND` if >= 0.60; else `NEUTRAL`; null if ratio null.
  - Distance to micro resistance = (micro_resistance_15m - last_price) / last_price * 100 (null if missing).

Expose as raw booleans/numerics only.

## Volume Logic (Simple, Intraday)

- `volume_multiple` = current 1m volume / median of last 30 completed 1m bars.
- No multi-session minute-of-day baseline (deferred).

## Resistance Interaction

- When last price enters a resistance cluster band: set `in_resistance_zone = true`.
- Compute `distance_to_next_cluster_pct` (to next higher cluster).
- No exit/entry signals—context only.

## Opening Range & Premarket

- `premarket_high`, `premarket_low` (04:00–09:30 ET)
- `opening_range_high`, `opening_range_low` (first 10 minutes RTH)
- `gap_pct` vs prior close

## Data Quality Gating

Snapshot fields:
- `status` (`ok|error`)
- `data_quality` (`ok|partial|stale|no_data|error`)
- `has_4h_data` (bool)
- `has_intraday_data` (bool)
- `has_market_data` (bool)
- `has_premarket_levels` (bool)
- `has_opening_range` (bool)

Degrade to `partial` if higher timeframe data missing; `stale/no_data` by quote age rules.
- Quote age thresholds: `stale_if_quote_age_ms = 5000`; `no_data_if_quote_age_ms = 60000`.
- Minimum 1m bars for MACD regime to be non-null: `macd_min_bars = 30`.
- Market proxy: use SPY (fallback QQQ if SPY unavailable). `is_market_green = (last - prior_close) / prior_close * 100 > 0` using prior_close; if unavailable set `has_market_data = false` and `is_market_green = null`.

## AE-1.1 Snapshot Schema (JSON)

```json
{
  "symbol": "AAPL",
  "as_of_ts_ms": 1700000000000,
  "as_of_et": "2026-02-07T09:30:00-05:00",
  "status": "ok",
  "data_quality": "ok",
  "has_premarket_levels": true,
  "has_opening_range": true,
  "regime": {
    "is_above_4h_ema": true,
    "is_above_open": true,
    "is_above_vwap": true,
    "is_market_green": false,
    "macd_regime": "bullish"
  },
  "volatility": {
    "intraday_range_pct": 1.8,
    "is_volatile_enough": true
  },
  "volume": {
    "volume_multiple": 2.4
  },
  "micro": {
    "micro_resistance_15m": 19.8,
    "micro_support_15m": 19.1,
    "range_5m_pct": 0.9,
    "range_15m_pct": 3.2,
    "compression_ratio": 0.28,
    "micro_state": "COIL",
    "dist_to_micro_r_pct": 0.5
  },
  "levels": {
    "resistance_clusters": [
      {
        "price_zone_low": 19.8,
        "price_zone_high": 20.1,
        "strength_score": 0.82,
        "timeframe_source": "4h"
      }
    ],
    "support_clusters": [
      {
        "price_zone_low": 18.2,
        "price_zone_high": 18.4,
        "strength_score": 0.77,
        "timeframe_source": "4h"
      }
    ],
    "nearest_resistance": {
      "price": 20.0,
      "source": "cluster_resistance",
      "distance_pct": 1.2
    },
    "nearest_support": {
      "price": 18.5,
      "source": "cluster_support",
      "distance_pct": -2.5
    },
    "in_resistance_zone": false,
    "distance_to_next_cluster_pct": 3.4
  },
  "levels_book": [
    {
      "low": 19.8,
      "high": 20.1,
      "side": "resistance",
      "scope": "macro",
      "base_strength": 0.82,
      "dynamic_influence": 0.86,
      "distance_pct": 1.5
    },
    {
      "low": 19.8,
      "high": 19.8,
      "side": "resistance",
      "scope": "micro",
      "base_strength": 0.3,
      "dynamic_influence": 0.44,
      "distance_pct": 0.5
    }
  ],
  "last_price": 19.7,
  "vwap": 19.5,
  "session": {
    "premarket_high": 19.2,
    "premarket_low": 18.7,
    "opening_range_high": 19.6,
    "opening_range_low": 19.1,
    "gap_pct": 4.2
  }
}
```

No trade readiness or suggestions. All fields deterministic.

## Time Windows (America/New_York)

- Premarket: 04:00–09:30 ET. `premarket_high/low` null before 04:00; fixed after 09:30.
- Opening range: 09:30–09:40 ET. `opening_range_high/low` null until 09:40; then fixed.
- VWAP anchor: 04:00–20:00 ET. Before 04:00, VWAP is null; after 20:00, hold last value.
- Micro ranges/windows: 5m = last 5 completed 1m bars; 15m = last 15 completed 1m bars.
- Levels influence: uses last 30 completed 1m bars for touch/rejection/break counting; distance decay clipped at 10%.

## AE-1.0 (Structural Profile)

On symbol load, store in SQLite `market_profile.profile_json`:
- `symbol`, `created_at_utc`
- top resistance clusters (as above)
- `is_above_4h_ema`, prior close, session open
- notes.method_version = `AE-1.0`
Raw bars are not stored.

## Constants (fixed)

- EMA period: 9 on 4h (daily fallback).
- Swing fractal lookback: 3 bars.
- Cluster band: 1.5% of price.
- Cluster cap: 3 resistance clusters and 3 support clusters.
- Recency decay: exp(-age / half_life); half_life_4h = 40 bars; half_life_daily = 60 bars.
- Volatility threshold: `intraday_range_pct > 1.0`.
- Volume baseline window: 30 completed 1m bars.
- Opening range window: first 10 minutes RTH.
- VWAP anchor: 04:00–20:00 ET.
- MACD: 12/26/9 on 1m.
- Quote age thresholds: stale_if_quote_age_ms = 5000; no_data_if_quote_age_ms = 60000.
- macd_min_bars = 30.
- Micro swing windows: 5 bars (5m), 15 bars (15m).
- Levels influence weights (deterministic):
  - base_strength (macro cluster strength_score; micro fixed 0.3)
  - touch_score weight 0.15 (touches/3 capped 1.0)
  - rejection_score weight 0.15 (rejections/3 capped 1.0; wick > body touching zone)
  - volume_score weight 0.10 (avg touch vol / median vol capped at 2.0 then /2)
  - clean_break_penalty weight -0.20 (clean breaks/2 capped 1.0; close >0.5% beyond with vol_mult>=2)
  - distance_decay weight -0.10 (|distance_pct|/10 capped 1.0)
  - Final dynamic_influence clipped to [0,1]; levels_book sorted by dynamic_influence desc then abs(distance_pct) asc.
- Market proxy: SPY. is_market_green:
  - Premarket (<09:30 ET): (last - prior_close) / prior_close * 100 > 0.
  - RTH/after (>=09:30 ET): compare last vs 09:30–09:31 1m bar close; if unavailable, fall back to prior_close and set has_market_data=false.
- RTH open: fetched via REST 1m bars at 09:30 ET; is_above_open uses this. If unavailable: is_above_open=null.
- Strength score: normalized 0..1 via `normalized_strength = min(1.0, raw_strength / (raw_strength + 1.0))`, raw_strength = touches * (0.5 + 0.5 * recency).
- Zero-width zones: if zone_low == zone_high, expand band by +/−0.01% of price (deterministic) to avoid zero width.

## Implementation Plan (high level)

Functions/modules to add:
1. **Data fetch/init**: fetch 4h (or daily) history, prior close, prior 3 dailies, session open; fetch market proxy (SPY/QQQ) last/percent.
2. **Structural extractor**:
   - `compute_ema_state(htf_bars) -> is_above_4h_ema`
   - `find_swings(htf_bars, lookback)`
   - `cluster_resistance(swings, band_pct, recency_half_life) -> clusters`
3. **Intraday aggregator**:
   - build 1m bars from 10s; maintain rolling 30-bar volume median; session highs/lows; VWAP.
4. **Boxes & regimes**:
   - `compute_macd_regime(1m_closes)`
   - `compute_vol_boxes(...)` for intraday_range_pct, is_volatile_enough
   - `compute_volume_multiple(current_1m_vol, median_30)`
5. **Levels & distances**:
   - track premarket/OR highs/lows, gap_pct
   - `nearest_support_resistance(last_price, clusters, vwap, OR/premarket levels)`
   - `in_resistance_zone` flag and `distance_to_next_cluster_pct`
6. **Snapshot builder**:
   - assemble AE-1.1 JSON with gating flags and status/data_quality.
7. **Storage**:
   - write AE-1.0 profile JSON to SQLite; keep AE-1.1 in memory (optionally cache last snapshot).

## Determinism Checklist

- Fixed constants documented; no adaptive heuristics.
- Capped cluster count and list sizes.
- No trade/entry/exit suggestions.
- No float turnover or multi-day minute baselines.
- VWAP anchor fixed (04:00–20:00 ET).
- Data quality gates based on quote age and data presence flags.
