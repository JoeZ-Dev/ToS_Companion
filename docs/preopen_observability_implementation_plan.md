# Pre-Open Observability and Evaluation Implementation Plan

## Purpose

This plan defines the next implementation cycle for ToS_Companion before the next fresh-market recording session.

The goal is to improve the value, traceability, and replayability of every recorded session without tuning the frozen micro-pullback detector or turning new contextual evidence into hard trade gates.

The existing six-session corpus remains development data. New recordings must remain prospectively collected and explicitly classified before detector-specific inspection.

## Non-negotiable guardrails

1. Do not change `MICRO_PULLBACK` semantics, thresholds, lifecycle rules, or configuration from the existing development corpus.
2. Do not tune `LOCAL_RESISTANCE_BREAKOUT` or `TIGHT_CONSOLIDATION_BREAKOUT` against the old six-session development corpus.
3. Do not add execution behavior, order placement, or automatic trade qualification.
4. New context such as volume, VWAP distance, HTB, relative strength, or session levels is evidence only unless separately validated later.
5. Live and replay must share the same event/observation contracts wherever practical.
6. Preserve backward compatibility with existing recordings. Additive schema changes are preferred.
7. Never fabricate L1 data. Historical repair rows retain explicit provenance.
8. Keep raw recording data immutable. Derived journals/reports may be regenerated.
9. Every persisted derived event must carry enough provenance to reproduce or audit it.
10. Any change that could alter existing detector output requires an explicit stop and review before merge.

## Current baseline

Integration branch:

`fix/repair-recording-gaps`

Current baseline after the two prospectively added breakout detectors:

`99c14ea6cd4d1bd9153bb95d4cf76d6c09c961a0`

Frozen micro-pullback detector semantic revision:

`33181b1ecf1bcce446a25ca136688342262262ea`

Current detector registry:

- `ASCENDING_TRIANGLE`
- `MICRO_PULLBACK`
- `LOCAL_RESISTANCE_BREAKOUT`
- `TIGHT_CONSOLIDATION_BREAKOUT`

The existing six sessions are development corpus. Holdout membership is explicit and currently empty.

---

# Phase 0 — Documentation and contracts first

## Objective

Define the data contracts before wiring new persistence or APIs.

## Work

Create or update documentation for:

- pattern-event journal schema;
- detector/config provenance schema;
- trigger-context snapshot schema;
- halt interval/event schema;
- outcome/forward-return schema;
- recording integrity report schema;
- session-level context primitives;
- volume evidence primitives;
- overlap/collision semantics;
- holdout reservation lifecycle;
- candidate/event export API;
- chart-overlay ownership and payload shape.

## Required design decisions

### Event identity

A persisted pattern event should contain, at minimum:

- session_id;
- symbol;
- pattern_id;
- pattern_type;
- state;
- observation timestamp;
- pattern started_at;
- detector revision/config fingerprint;
- source mode: live/replay;
- evidence payload;
- geometry payload where present.

### Versioning

Every recording/session manifest should record:

- application Git revision;
- enabled detector names;
- detector implementation revision or semantic freeze revision where defined;
- detector configuration values or deterministic config fingerprint;
- recording schema version;
- derived-journal schema version;
- evaluator baseline revision where applicable.

### Derived-data rule

Pattern journals, outcome tables, integrity reports, and exports are derived artifacts. Raw L1/candle recording files remain canonical and immutable.

## Exit criteria

- schemas documented;
- ownership boundaries documented;
- no runtime behavior changed.

---

# Phase 1 — Capture foundation

This phase should be completed before relying on the next live session for research.

## 1A. Detector and runtime provenance in recording manifests

### Objective

Make every new recording self-describing.

### Add

At recording/session creation, persist:

- app revision;
- enabled detector inventory;
- detector config snapshot/fingerprint;
- frozen detector revision metadata where defined;
- bar cadence used for pattern evaluation;
- timezone/session metadata;
- recording format/schema version.

### Constraints

- old manifests remain readable;
- missing provenance on legacy recordings is represented as unknown, not guessed.

## 1B. First-class pattern-event journal

### Objective

Persist exact live detector state transitions instead of relying only on replay reconstruction later.

### Persist events such as

`VALID -> TESTING -> BREAKOUT`

`PULLBACK -> TURNING -> CONTINUATION`

Each journal event should include:

- pattern identity;
- state;
- timestamp;
- evidence;
- semantic geometry;
- detector/config provenance;
- whether the event came from live ingestion or replay regeneration.

### Important

Do not create duplicate journal rows every time an unchanged observation is emitted. Prefer meaningful state/evidence transitions with deterministic identity.

Replay reconstruction must remain available and should be comparable against the live journal.

## 1C. Halt/status event history

### Objective

Record status transitions as events rather than retaining only current security status.

Capture when available:

- halted/suspended state entered;
- resume/trading state restored;
- exchange/security status value;
- source timestamp;
- observed timestamp;
- any provider-supplied reason/code if available.

Do not infer a halt merely from absence of trades.

Derived halt intervals may later be assembled from explicit status transitions.

## 1D. Recording integrity report

### Objective

At session close, or on demand, produce a machine-readable quality report.

Per symbol include:

- first/last event timestamp;
- raw event count;
- historical repair-row count;
- detected gaps;
- repaired gaps;
- unresolved gaps;
- max gap duration;
- halt intervals/status events;
- pattern-event counts by detector/state;
- whether provenance metadata is complete;
- warnings that materially affect replay confidence.

Session rollup should summarize all symbols.

## 1E. Holdout reservation workflow

### Objective

Allow future sessions to be reserved without editing source code.

Preferred implementation:

- small persisted registry/config under application data;
- API/CLI to classify a session as `development`, `holdout`, or `unclassified`;
- default remains `unclassified`;
- reservation timestamp and optional note;
- protection against silently relabeling an inspected holdout without an explicit action.

The repository-level registry remains useful for fixed historical baselines, but future session classification should not require a code deployment.

## Phase 1 exit criteria

A new live recording can answer:

- exactly what detector code/config was running;
- exactly what pattern states were observed live;
- whether status/halt transitions occurred;
- whether recording coverage is complete enough for replay;
- whether the session was reserved as holdout before inspection.

---

# Phase 2 — Outcome and excursion measurement

## Objective

Automatically attach objective post-event behavior to pattern instances without deciding whether the setup was good or bad.

## 2A. Wire MAE/MFE to pattern instances

Use the existing excursion utilities rather than duplicating the math.

For each trigger-state event where sufficient future data exists, derive:

- entry/reference price used for measurement;
- MFE percentage;
- MAE percentage;
- timestamp/time-to-MFE;
- timestamp/time-to-MAE;
- maximum favorable price;
- maximum adverse price;
- measurement horizon;
- whether the horizon was truncated by end-of-recording/data gap/halt.

Do not label profitability or strategy quality from these values.

## 2B. Forward-return ladder

Measure deterministic returns at:

- +1 minute;
- +2 minutes;
- +5 minutes;
- +10 minutes;
- +15 minutes.

Where exact timestamps are unavailable, document and use one consistent bar-selection rule.

Store unavailable values as unavailable, never fabricated/interpolated.

## 2C. Structural invalidation measurement

Where a detector exposes a defensible structural invalidation level, record:

- invalidation level;
- first breach timestamp;
- time from trigger to invalidation.

Do not invent invalidation rules for detectors that do not expose one.

## Phase 2 exit criteria

Pattern events can be evaluated later without rerunning bespoke scripts for basic forward behavior.

---

# Phase 3 — Context evidence primitives

These values are descriptive evidence, not hard gates.

## 3A. Trigger-context snapshot

At the matched/live trigger transition persist a snapshot containing whatever is available at that instant:

- last/mark price;
- VWAP and percent distance to VWAP;
- day percentage change;
- relative-strength rank within watched momentum symbols;
- security status;
- halt state;
- HTB flag/quantity/rate;
- shortable state;
- float/fundamental context with source/availability marker;
- session phase;
- current volume evidence;
- relevant session levels.

Every field must distinguish `unavailable` from zero/false.

## 3B. Reusable volume primitives

Add generic structure helpers, not detector-specific gates.

Candidate primitives:

- recent mean/median volume;
- pullback/consolidation volume contraction ratio;
- current breakout-volume expansion ratio;
- local relative volume against prior N completed bars;
- volume trend over a structure.

Expose evidence first.

Do not require volume confirmation for any current detector in this phase.

## 3C. Session-level primitives

Create one reusable session context provider for:

- premarket high/low;
- regular-session HOD/LOD;
- opening-range high/low once defined;
- prior-day high/low/close when source data supports it;
- VWAP;
- distance from current price to those levels.

Avoid recomputing session semantics independently inside named detectors.

The opening-range duration must be explicit configuration, not an implied constant hidden inside a detector.

## Phase 3 exit criteria

Any future detector can consume standardized context without duplicating session/volume calculations.

---

# Phase 4 — Pattern overlap and collision analysis

## Objective

Understand when multiple detectors are describing the same underlying price structure.

## Add

For each symbol/time window, derive overlap records when pattern instances coexist.

Capture:

- involved pattern IDs/types;
- overlap start/end;
- trigger-state times;
- shared/nearby structural levels;
- whether one trigger occurred inside another pattern's active lifetime.

Do not suppress or merge detectors yet.

This is research evidence for later taxonomy decisions.

## Exit criteria

We can quantify, for example, how often:

- ascending triangle + local resistance breakout;
- local resistance breakout + tight consolidation breakout;
- micro pullback + another breakout structure

describe the same market episode.

---

# Phase 5 — Candidate/event research export

## Objective

Give Codex/ChatGPT and offline analysis one compact machine-readable interface instead of requiring chart scraping.

## API/export should provide

For a requested session/symbol or corpus:

- recording provenance;
- integrity status;
- each pattern instance;
- complete state-transition journal;
- detector evidence/geometry;
- trigger-context snapshot;
- halt/status context;
- overlap records;
- MAE/MFE;
- forward-return ladder;
- invalidation timing where available.

Support deterministic filtering by:

- session;
- symbol;
- pattern type;
- corpus classification;
- trigger-state presence;
- time range.

## Constraints

- API is read-only;
- no hindsight fields should leak into a blind pre-trigger review endpoint;
- outcome fields must be separable from trigger-time evidence.

## Exit criteria

A research agent can consume structured setup evidence without visually interpreting the live frontend.

---

# Phase 6 — Browser chart overlays

## Objective

Render detector geometry for human sanity checking while preserving detector/UI separation.

## Render

- ascending-triangle resistance + rising support;
- micro-pullback impulse/pullback/recovery geometry where available;
- local-resistance horizontal level;
- tight-consolidation range high/low;
- trigger marker/state transitions.

## UX requirements

- overlays must not reset zoom/pan;
- overlays update independently from chart viewport state;
- allow pattern families to be hidden/shown;
- avoid clutter from stale/completed instances;
- tooltip/details should expose detector evidence and timestamps;
- no order/trade controls added as part of this work.

## Exit criteria

A human can visually confirm what the detector believed without changing the detector.

---

# Phase 7 — Hardening and replay parity

## Objective

Verify live capture and replay reconstruction agree.

## Required checks

For representative recordings:

- replay regenerates equivalent pattern IDs/state transitions where deterministic;
- live journal and regenerated journal differences are reported rather than silently ignored;
- context snapshots do not use future data;
- outcome metrics begin strictly after the trigger/reference timestamp;
- repaired historical candles retain provenance in downstream reports;
- halt intervals do not get inferred from missing data;
- integrity reports handle active/incomplete sessions safely;
- legacy recordings without new metadata still load.

Add regression tests around all new schemas and boundaries.

## Exit criteria

CI green, docs current, live/replay parity documented, no detector semantic drift.

---

# Suggested implementation order

For maximum value before the next market session:

1. Phase 0 contracts/documentation.
2. Phase 1A provenance.
3. Phase 1B pattern-event journal.
4. Phase 1C halt/status history.
5. Phase 1D integrity report.
6. Phase 1E holdout reservation workflow.
7. Phase 2 outcome/MAE/MFE/forward returns.
8. Phase 3 trigger-context snapshots.
9. Phase 3 volume primitives.
10. Phase 3 session-level primitives.
11. Phase 4 overlap analysis.
12. Phase 5 candidate/event export.
13. Phase 6 overlays.
14. Phase 7 hardening/parity.

If time becomes constrained, finish Phases 0-2 before moving to UI work.

---

# PR discipline

Use small, reviewable PRs. Recommended boundaries:

- PR A: contracts/docs only;
- PR B: recording provenance + manifest compatibility;
- PR C: pattern-event journal;
- PR D: halt/status event history;
- PR E: integrity report + API;
- PR F: persistent corpus/holdout workflow;
- PR G: outcome/MAE/MFE/forward returns;
- PR H: context snapshot infrastructure;
- PR I: volume primitives;
- PR J: session-level primitives;
- PR K: overlap analysis;
- PR L: research export API;
- PR M: browser overlays;
- PR N: parity/hardening/docs closeout.

Do not combine detector changes with observability/infrastructure PRs.

For each PR:

1. inspect current code before editing;
2. preserve existing contracts unless additive change is sufficient;
3. add tests before merge;
4. run Linux/core and browser CI;
5. inspect failures rather than weakening tests;
6. merge only when relevant CI is green;
7. update documentation in the same PR when its contract changes.

---

# Explicitly out of scope for this cycle

- trading execution;
- automatic entries/exits;
- risk sizing;
- profitability optimization;
- threshold tuning from the existing development corpus;
- adding old development annotations as aliases for the two new prospective detectors;
- using context factors as hard setup gates;
- fabricating missing market data;
- rewriting raw recordings.

The purpose of this cycle is to make future market data maximally useful and scientifically traceable before making more strategy decisions.
