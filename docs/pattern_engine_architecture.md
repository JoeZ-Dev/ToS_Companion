# Pattern engine architecture

## Purpose

The pattern engine identifies deterministic market structures from normalized intraday bars and emits structured observations that can be consumed by:

- live analysis;
- recorded-session replay;
- setup/candidate generation;
- browser/WebSocket state;
- chart overlays;
- later research and outcome analysis.

Pattern detection is intentionally separate from trade qualification and execution.

A detector may say that a micro pullback or ascending triangle exists. That does **not** mean ToS_Companion should enter a trade.

## Architectural rule

The core pattern framework must not know the list of supported pattern names.

Adding a future pattern must not require editing:

- `PatternEngine`;
- `PatternObservation`;
- the shared structure primitives;
- execution logic;
- UI code.

Named patterns are plugins to the internal registry.

This is an internal plugin model, not an external ChatGPT/plugin package.

## Current layout

```text
src/momentum_companion/setup_engine/
    pattern_contracts.py
    pattern_engine.py

    structure/
        __init__.py
        bars.py
        swings.py
        levels.py
        impulse.py
        retracement.py

    patterns/
        __init__.py
        ascending_triangle.py
        micro_pullback.py
```

## Data flow

```text
live Schwab events OR recorded replay events
                  |
                  v
            bar aggregation
                  |
                  v
        normalized market structure
                  |
                  v
       reusable structure primitives
                  |
                  v
          registered detectors
                  |
                  v
          PatternObservation[]
             /           \
            v             v
     setup generation   UI/chart
```

Live and replay should eventually feed the same detector pipeline.

## Reusable structure primitives

Named detectors should consume reusable structural facts instead of reimplementing them.

Current primitives include:

### Bars

`structure/bars.py`

Normalizes supported bar objects/dictionaries into a common `NormalizedBar` shape.

### Swings

`structure/swings.py`

Extracts deterministic swing highs and swing lows.

### Levels

`structure/levels.py`

Clusters nearby swing points into horizontal price levels.

This is useful for resistance/support concepts shared by:

- ascending triangles;
- flat-top breakouts;
- consolidation breakouts;
- failed breakouts;
- future support/resistance structures.

### Impulse

`structure/impulse.py`

Finds a recent bullish impulse leg.

This is useful for:

- micro pullbacks;
- bull flags;
- pennants;
- first pullback setups;
- future momentum-continuation structures.

### Retracement

`structure/retracement.py`

Measures the pullback following an impulse:

- low price;
- low timestamp;
- duration;
- retracement depth.

This is shared infrastructure for continuation patterns rather than logic owned by `MICRO_PULLBACK`.

## Pattern contract

Every detector returns either:

```python
PatternObservation
```

or:

```python
None
```

`PatternObservation` contains:

- `symbol`;
- `pattern_type` as an open string;
- `state`;
- `started_at`;
- `updated_at`;
- measurable `evidence`;
- significant chart `points`;
- chart `lines`.

Pattern names are strings rather than a closed enum so new patterns do not require framework changes.

Example:

```python
PatternObservation(
    symbol="ABCD",
    pattern_type="ASCENDING_TRIANGLE",
    state=PatternState.TESTING,
    started_at=...,
    updated_at=...,
    evidence={
        "resistance_touches": 3,
        "support_slope_per_sec": 0.0021,
        "compression_pct": 61.0,
    },
    points=[...],
    lines=[...],
)
```

## Pattern states

The shared state vocabulary currently includes:

- `FORMING`;
- `VALID`;
- `TESTING`;
- `IMPULSE`;
- `PULLBACK`;
- `TURNING`;
- `BREAKOUT`;
- `CONTINUATION`;
- `INVALIDATED`.

Not every detector must use every state.

States describe the detector's observed structure. They are not execution commands.

## Detector interface

A detector must expose:

```python
name: str

def detect(self, symbol: str, bars: Iterable) -> PatternObservation | None:
    ...
```

The core engine depends only on this interface.

Conceptually:

```python
class PatternDetector(Protocol):
    name: str

    def detect(self, symbol: str, bars: Iterable) -> PatternObservation | None:
        ...
```

## Registration

### Critical rule

**New patterns are registered outside `PatternEngine`.**

Do not add imports or pattern-specific branches to `pattern_engine.py`.

The current application-level registry is assembled in:

```text
src/momentum_companion/setup_engine/patterns/__init__.py
```

using:

```python
def build_default_pattern_engine() -> PatternEngine:
    engine = PatternEngine()
    engine.register(AscendingTriangleDetector())
    engine.register(MicroPullbackDetector())
    return engine
```

This is the supported registration point for enabled production detectors.

### Adding a future pattern

Suppose the next pattern is `BULL_FLAG`.

1. Add a detector module:

```text
patterns/bull_flag.py
```

2. Reuse existing structure primitives where possible.

For example:

```python
from dataclasses import dataclass

PATTERN_NAME = "BULL_FLAG"

@dataclass(frozen=True)
class BullFlagDetector:
    name: str = PATTERN_NAME

    def detect(self, symbol, bars):
        # normalize bars
        # find impulse
        # measure controlled consolidation/retracement
        # validate flag geometry
        # return PatternObservation or None
        ...
```

3. Register it in the application registry:

```python
from momentum_companion.setup_engine.patterns.bull_flag import BullFlagDetector

def build_default_pattern_engine() -> PatternEngine:
    engine = PatternEngine()
    engine.register(AscendingTriangleDetector())
    engine.register(MicroPullbackDetector())
    engine.register(BullFlagDetector())
    return engine
```

4. Add detector-specific tests.

5. Add or extend shared structure primitives only when the concept is reusable beyond the new pattern.

### What must NOT change when registering a pattern

Adding `BULL_FLAG` should not require modifying:

```text
pattern_engine.py
pattern_contracts.py
execution/*
ui/*
web/*
```

unless a genuinely new generic capability is required.

## Duplicate registration

`PatternEngine.register()` rejects duplicate detector names.

Example:

```python
engine.register(BullFlagDetector())
engine.register(BullFlagDetector())  # raises ValueError
```

Detector names therefore act as registry identities and must be stable.

Use uppercase descriptive names such as:

```text
ASCENDING_TRIANGLE
MICRO_PULLBACK
BULL_FLAG
FLAT_TOP_BREAKOUT
OPENING_RANGE_BREAKOUT
VWAP_RECLAIM
```

## Why registration is explicit

Automatic module discovery is intentionally deferred.

Explicit registration currently provides:

- deterministic startup;
- obvious enabled/disabled pattern inventory;
- easy testing;
- no import-time filesystem scanning;
- simple configuration control;
- fewer surprises in live trading software.

If the pattern library becomes large, registration can later be driven by configuration without changing the detector interface.

For example, a future configuration layer could enable:

```yaml
patterns:
  - ASCENDING_TRIANGLE
  - MICRO_PULLBACK
  - BULL_FLAG
```

The engine should still receive instantiated detectors through the same `register()` API.

## Current reference implementations

### Ascending triangle

Consumes:

- normalized bars;
- swing highs/lows;
- clustered resistance;
- rising-low geometry.

Currently emits evidence including:

- resistance level/range;
- number of resistance touches;
- number of higher lows;
- rising-support slope;
- compression percentage;
- breakout level.

### Micro pullback

Consumes:

- normalized bars;
- strongest recent bullish impulse;
- measured retracement.

Currently emits evidence including:

- impulse start/high;
- impulse percentage;
- pullback low;
- duration;
- retracement depth;
- continuation level.

These two detectors are reference implementations for the framework, not special cases built into it.

## Future pattern families

Likely future momentum-oriented detectors include:

### Compression / breakout

- flat-top breakout;
- consolidation breakout;
- bull pennant;
- symmetrical triangle;
- wedge;
- inside-range compression.

### Momentum continuation

- bull flag;
- first pullback;
- micro pullback variants;
- HOD pullback/continuation.

### Session / level interaction

- opening-range breakout;
- premarket-high breakout;
- VWAP reclaim;
- VWAP pullback;
- prior-high reclaim.

### Failure / reversal

- failed breakout;
- failed HOD;
- exhaustion/rejection structures.

These should first be decomposed into reusable structural concepts before adding detector-specific code.

## Design rule for new primitives

Before putting logic inside a named detector, ask:

> Could another momentum pattern reasonably use this concept?

If yes, prefer adding it under `structure/`.

Examples:

Good reusable primitives:

- range compression;
- volume contraction;
- volume expansion;
- slope/trend;
- distance to VWAP;
- session levels;
- relative volume;
- breakout/reclaim;
- rejection;
- consolidation duration.

Pattern-specific logic should primarily compose these primitives and manage pattern-specific state.

## Configuration versus code

Do not force all patterns into YAML or other declarative configuration.

Use a hybrid model:

```text
reusable primitives
       |
       v
detector configuration
       |
       v
pattern-specific evaluator
       |
       v
PatternObservation
```

Simple threshold-based patterns may eventually be largely declarative.

Patterns requiring session context, state history, failure/reclaim behavior, or specialized geometry should remain procedural Python detectors.

## Chart ownership

Detectors do not manipulate the chart.

They emit semantic geometry:

- points;
- lines;
- later, potentially zones/ranges.

Presentation layers render that geometry.

This keeps the same observation usable by:

- desktop Lightweight Charts;
- browser Lightweight Charts;
- replay;
- analysis logs.

## Live/replay integration rule

The source-agnostic integration boundary now exists as:

```text
src/momentum_companion/setup_engine/pattern_service.py
```

`PatternEvaluationService` owns a bounded rolling bar window per symbol and exposes the same detector path to any source.

Primary interfaces:

```python
service.ingest_completed_bar(symbol, bar)
service.seed_bars(symbol, bars)
service.observations(symbol)
service.reset(symbol)
```

The intended flow is:

```text
Live:
Schwab -> 10s completed bar -> PatternEvaluationService -> PatternEngine

Replay:
recorded market events -> same 10s completed bar shape
                       -> PatternEvaluationService
                       -> PatternEngine
```

`PatternEvaluationService` does not know whether a bar came from Schwab, replay, historical seeding, or a test fixture.

There must not be separate live and replay pattern implementations.

Replay is intended to validate:

- false positives;
- missed patterns;
- state transitions;
- threshold choices;
- eventual outcome statistics.

## Execution boundary

Pattern detection remains observational.

The future flow should remain:

```text
PatternEngine
    |
    v
PatternObservation
    |
    v
setup/candidate qualification
    |
    v
risk/trade gates
    |
    v
execution
```

A detected pattern is evidence available to strategy logic, not permission to trade.

## Current implementation status

As of this branch:

- core registry/orchestrator exists;
- detector interface exists;
- open pattern-name contract exists;
- reusable structure package exists;
- ascending triangle reference detector exists;
- micro pullback reference detector exists;
- explicit default registration exists;
- duplicate registration is rejected;
- synthetic pattern tests exist;
- pattern-only CI passes;
- source-agnostic `PatternEvaluationService` exists;
- live/replay completed-bar boundary is covered by tests.

Current observational live integration:

- completed 10-second bars in `CompanionRuntime._handle_completed_bar()` are passed to `PatternEvaluationService`;
- resulting observations are stored in `CompanionSession`;
- the session emits `pattern_update` events;
- pattern observations are included in normal session snapshots and therefore are available through the existing browser state/WebSocket channel;
- pattern failures are isolated from AE ingestion so pattern evaluation cannot stop existing analysis processing.

Current browser presentation:

- active patterns are shown in a dedicated browser panel;
- pattern name, state, and concise detector evidence are displayed;
- detector-supplied `lines` are rendered directly on Lightweight Charts;
- clicking a pattern emphasizes its rendered geometry;
- overlays are rebuilt only when the pattern set, active symbol, or selected pattern changes, not on every quote;
- the browser does not infer or recompute pattern geometry.

Still not integrated:

- setup candidate generator;
- desktop chart overlays;
- execution logic.

The runtime and browser integration remain observational only. No pattern can trigger or qualify an order at this stage.
