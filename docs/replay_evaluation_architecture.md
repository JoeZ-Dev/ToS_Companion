# Replay and Evaluation Architecture

## Purpose

Replay is the deterministic evaluation boundary for ToS_Companion. It is not a second trading runtime and it must not become an alternate strategy implementation.

Recorded market evidence is replayed through the same bar aggregation, Analysis Engine (AE), and pattern evaluation services used by live operation. Replay owns isolated state and a simulated market clock so historical runs cannot mutate live state, recorder state, Schwab subscriptions, or live analysis.

## Core invariants

1. Recorded evidence is immutable. Replay only reads recording session files.
2. No future leakage. Historical replay must not fetch current/future intraday data to fill missing context.
3. Same analysis path. L1 deltas feed LevelOneCache, BarAggregator10s, AEEngine, and PatternEvaluationService.
4. Replay clock owns time. Analysis timestamps and time-sensitive calculations use the replay event timestamp.
5. Seek means rebuild. Rewinding discards replay analysis state and deterministically replays from the beginning to the target cursor.
6. Live remains live. Replay uses a separate CompanionSession; live WebSocket/Schwab processing continues independently.
7. Training is evaluation first. Replay may measure and label strategy behavior, but it must never silently tune live parameters.

## Current recording evidence

A market-day session contains:

- manifest.json
- one SYMBOL.jsonl file per recorded ticker
- raw LEVELONE_EQUITIES deltas
- Schwab stream timestamps
- local receive timestamps
- symbol lifecycle/count information

This supports deterministic reconstruction of:

- L1 bid/ask/last/volume state
- 10-second bars
- minute aggregation
- VWAP/session high/session low
- premarket and opening-range structure when the recording covers those periods
- intraday AE metrics
- pattern-engine observations

## Known context gap

Existing sessions do not necessarily contain all inputs used by the live AE profile, especially:

- higher-timeframe price history
- prior close / higher-timeframe swing clusters
- broad-market proxy context
- historical data from before a ticker was enrolled, except where available elsewhere

Replay must represent this as partial context. It must not query today's Schwab REST state and pretend that result was known at the historical replay timestamp.

For future recordings, the recorder should capture a symbol enrollment context snapshot when a ticker is added. That snapshot should contain the exact historical inputs the live runtime used at enrollment, including the intraday 1-minute history through that timestamp and the AE/profile context needed to recreate the decision environment.

## Current Replay module

### Catalog

momentum_companion.replay.catalog.RecordingCatalog

- lists persisted sessions
- exposes recorded symbols/counts
- validates session identifiers
- loads immutable per-symbol L1 events
- preserves deterministic event ordering

### Engine

momentum_companion.replay.engine.ReplayEngine

Owns:

- independent CompanionSession
- independent LevelOneCache
- independent BarAggregator10s
- independent AEEngine
- independent PatternEvaluationService
- replay cursor and simulated clock

Controls:

- load session/ticker
- play at 1x, 5x, 20x, or max
- pause
- step one or more recorded events
- seek by event cursor

### Browser

Replay is exposed under /api/replay/* and the Replay tab.

The main chart is reused as a view surface only. Entering Replay renders isolated replay state. Leaving Replay restores the live view. The live backend continues processing while Replay is open.

## Evaluation/training roadmap

Replay should become the common substrate for strategy research.

### Phase 1: Fidelity

Goal: prove that the same recorded input always produces the same bars, AE states, and pattern observations.

Metrics:

- event count consumed
- bar fingerprints
- pattern observation timestamps
- AE snapshot fingerprints
- missing/partial context flags

A replay that is not deterministic is invalid for training.

### Phase 2: Human opportunity labels

Allow a replay user to mark:

- opportunity start
- ideal/acceptable entry area
- invalidation/stop area
- setup type
- whether the move was tradable
- notes/reasoning

Labels must live outside immutable raw recordings and reference:

- recording session id
- symbol
- replay timestamp/cursor
- strategy/pattern version

This creates a ground-truth review set without changing the source data.

### Phase 3: Outcome measurement

For each detector observation or human label, measure forward price behavior from recorded evidence:

- maximum favorable excursion (MFE)
- maximum adverse excursion (MAE)
- time to target
- time to stop/invalidation
- continuation duration
- pullback depth
- breakout follow-through
- failure/reclaim behavior

These are measurements, not recommendations.

### Phase 4: Deterministic simulated execution

Add a simulator that owns:

- replay clock
- candidate entry orders
- fill assumptions based on available evidence tier
- stops/targets
- position/P&L state
- halts and gaps when observable
- transaction/slippage assumptions

The simulator must remain separate from the pattern detector. A pattern says what it sees; the simulator measures what a defined execution policy would have produced.

### Phase 5: Strategy comparison

Run multiple immutable strategy/config versions against the same recording corpus and compare descriptive results:

- detections
- false/late detections
- missed labeled opportunities
- MFE/MAE distributions
- stop/target outcomes
- latency from structural confirmation to signal
- behavior by time of day and setup type

Do not modify live thresholds based on a single session. Candidate parameter changes should be versioned and evaluated against a growing holdout corpus.

## Data-quality tiers

Replay results must retain the evidence tier used:

1. TNS_L1: true time-and-sales plus L1
2. L1: quote/last/volume deltas
3. BAR_10S: aggregated evidence
4. BAR_1M: historical fallback/context only

Current recordings are primarily L1. Simulated execution claims must not imply trade-level precision that the source recording does not contain.

## Next capture improvement

When a symbol is first added to recording, persist a context bundle beside the raw event file:

- 1-minute candles from 04:00 ET through enrollment time
- AE/profile inputs available at that moment
- market proxy context available at that moment
- enrollment timestamp
- schema/version identifiers

This makes future recordings self-contained replay fixtures and removes dependence on later Schwab REST availability.
