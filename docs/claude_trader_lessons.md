# Claude_Trader lessons worth adopting in ToS_Companion

## Purpose

This document records architecture and workflow ideas observed in `JoeZ-Dev/claude-trader` that are worth considering for ToS_Companion.

The intent is **not** to import Claude_Trader's strategy assumptions as truth. Its current momentum rules, entry timing, stop behavior, and volume gates remain hypotheses and should be validated empirically.

## Ideas worth adopting

### 1. Recorder-first architecture

Treat live market data as evidence that should be preserved for later replay and analysis.

The system should be able to:
- consume live market events;
- persist replayable raw market data;
- replay those events through the same analysis path later;
- evaluate strategy behavior independently of the live session.

This direction aligns with the new intraday recorder and future simulator work.

### 2. Multi-symbol monitoring

ToS_Companion is currently organized primarily around one active symbol in the desktop controller.

Claude_Trader's ability to monitor a small number of symbols concurrently is a better fit for discretionary momentum trading, where the user may watch only a handful of manually selected candidates at once.

A scanner is not required yet. Manual candidate selection is acceptable.

### 3. Deterministic strategy logic outside the LLM

Trading rules, setup state, entry eligibility, exit state, and execution simulation should be deterministic Python logic.

The LLM may provide:
- narration;
- contextual interpretation;
- summaries;
- human-facing explanation.

The LLM should not be the authoritative source for:
- whether a setup exists;
- whether a trade is entered;
- where a simulated fill occurs;
- where a stop triggers.

### 4. Explicit setup taxonomy

Claude_Trader models setup types explicitly, including concepts such as:
- resistance breakout;
- micro breakout;
- VWAP reclaim;
- round-number reclaim.

ToS_Companion already has richer analysis, but a more explicit setup-state layer would make:
- evaluation easier;
- journaling cleaner;
- replay comparison easier;
- strategy statistics more meaningful.

These setup types should be treated as testable hypotheses, not fixed truths.

### 5. Incremental realtime calculations

Claude_Trader improved realtime performance by updating indicators and state incrementally rather than recomputing complete histories on every new event.

ToS_Companion should prefer incremental updates for:
- VWAP;
- EMA;
- MACD;
- relative volume;
- setup state;
- hold confirmation;
- other rolling indicators where practical.

This becomes more important when several symbols are monitored concurrently.

### 6. Cleaner separation of live state

Claude_Trader separates:
- market stream state;
- deterministic analysis state;
- journal state;
- UI state.

ToS_Companion currently mixes a substantial amount of application behavior directly into the Qt `UIController`.

A browser/server refactor should preserve this lesson by separating headless application state from presentation state.

### 7. Dedicated retrospective analysis

Claude_Trader has a dedicated retrospective analysis layer, even though its present statistics are still basic.

ToS_Companion should eventually have an evaluation layer separate from the trading UI that can analyze:
- win/loss distributions;
- expectancy;
- R multiples;
- profit factor;
- drawdown;
- MAE/MFE;
- time in trade;
- setup type;
- time of day;
- RVOL/liquidity bands;
- candidate-selection metadata;
- replayed forward outcomes.

## Ideas not to adopt as validated strategy

Do not import these as trusted rules without evidence:
- 30-second setup confirmation;
- 10-second bar-close entries;
- exact modeled stop fills;
- current Claude_Trader stop-transition behavior;
- its current volume gates;
- any setup ranking or parameter values.

These may be useful experiment variables, but they are not established edge.

## Target combined direction

The desired direction is:

**ToS_Companion's richer analysis + cleaner realtime separation + raw recorder/replay + deterministic strategy evaluation + browser deployment on joelab.**

ToS_Companion should become a market experiment platform that can also support live discretionary trading, rather than only a desktop trading assistant.
