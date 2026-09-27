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

### Manifest contract

Manifest schema version 2 adds a top-level `provenance` object while preserving
the schema-version-1 raw market-event rows. The object contains:

- `application`: Git revision, dirty-worktree state when observable, and package
  version when installed;
- `detectors.enabled`: detector name, complete config value, deterministic config
  fingerprint, and a semantic revision when one is frozen;
- `detectors.inventory_fingerprint`: a deterministic fingerprint of the enabled
  detector/config/revision inventory;
- `schemas`: manifest, raw market-event, and derived-journal schema versions;
- `pattern_evaluation.bar_cadence_seconds`;
- `session`: timezone and explicit premarket, regular-session, after-hours, and
  recording-cutoff boundaries;
- `source_mode`.

Catalog reads normalize legacy manifests to the same shape with unavailable
values represented by `null`. They do not infer which detectors or cadence were
used by an old recording. Source checkouts resolve the Git revision directly;
the joelab Docker deployment injects the checked-out revision as a build
argument because the image does not contain the repository's `.git` directory.

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

### Journal contract

New recording sessions declare `pattern_events.jsonl` as a derived artifact in
the manifest. Each schema-version-1 row records the session and symbol, stable
pattern ID and type, detector state, pattern-start and observation timestamps in
milliseconds, evidence, point/line geometry, detector config fingerprint and
frozen semantic revision when defined, source mode, and deterministic event and
snapshot fingerprints. The live observation timestamp is the completed bar that
caused evaluation.

The writer appends a row when state, evidence, or semantic geometry changes for
a pattern ID. Repeated identical snapshots are skipped. Absence from a later
stateless detector result does not create an inferred invalidation. Legacy
sessions without the artifact load with an empty journal; raw event files remain
unchanged and replay reconstruction remains independent.

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

### Status-event contract

New sessions declare `security_status_events.jsonl` as a derived artifact. A
schema-version-1 event is written only when a raw `LEVELONE_EQUITIES` delta
explicitly contains Schwab security-status field `32`, and only when its status,
provider reason, or provider reason code differs from the last explicit value
for that symbol. Each row keeps the provider value, optional reason/code without
reinterpretation, the message timestamp as `provider_ts_ms`, the recorder receipt
time as `observed_at_utc`, the timestamp source, and deterministic identity.

No event or halt interval is inferred from quote silence, a data gap, or a cached
status copied onto a normalized quote. Legacy sessions without the artifact load
with an empty status history.

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

### Integrity-report contract

`integrity_report.json` schema version 1 is generated when a new recording
closes. The same report can be calculated without writing files through
`GET /api/recordings/{session_id}/integrity`. Reports include per-symbol first
and last raw L1 timestamps, raw and repaired-row counts, gaps over 60 seconds,
full versus unresolved minute-candle repairs, maximum gap duration, explicit
status/halt counts, pattern counts by detector/state, provenance completeness,
and machine-readable replay-confidence warnings. A session rollup totals these
fields.

Gap status is calculated from adjacent raw L1 timestamps. A gap is fully
repaired only when a historical one-minute row exists for every intervening
minute boundary. Status silence never changes gap classification and never
creates a halt. On-demand calculation is read-only; legacy sessions report
missing provenance and unavailable derived journals rather than guessing.

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

### Classification contract

Corpus classifications are stored under application data in
`corpus_classifications.json`, outside immutable recording directories. Unknown
and newly recorded sessions resolve to `unclassified` without needing a stored
row. The API lists classifications and supports get/update at
`/api/corpus/classifications/{session_id}`. Each change records its timestamp,
note, previous value, and new value.

The repository's six historical development sessions remain fixed baselines.
Once a future session is marked `holdout`, moving it to another corpus requires
`confirm_holdout_relabel=true`; the confirmation is recorded in its history.
Review recording listings and detector-audit metadata use this persisted value.
An unreadable registry fails closed instead of reverting reserved sessions to
the default classification.

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

### Outcome-measurement contract

`pattern_outcomes.json` schema version 1 is generated at recording close and is
available read-only from
`GET /api/evaluation/pattern-outcomes/{session_id}`. The first live journal event
in `BREAKOUT` or `CONTINUATION` for each pattern ID is the descriptive trigger.
The completed trigger-bar close is the reference price. Measurements reuse
`compute_excursions` for long-side MAE/MFE and add extrema timestamps and elapsed
times.

The default horizon is 15 minutes. Forward returns at 1, 2, 5, 10, and 15
minutes use the first observed bar timestamp at or within 10 seconds after the
target; unavailable observations remain `null` and are never interpolated. The
horizon stops at recording end, the first unresolved raw gap, or an explicit
provider halt. Fully repaired minute gaps remain measurable and are flagged.

Structural invalidation is measured only for a detector-provided
`invalidation_level`, plus the tight-consolidation detector's existing explicit
`breakdown_level` and close-breach rule. No invalidation level is inferred for
other patterns.

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

### Trigger-context contract

Live `BREAKOUT` and `CONTINUATION` journal transitions carry an additive
`trigger_context` schema-version-1 snapshot captured after calculations for the
same completed bar. Each evidence value has `available`, `value`, and `source`
fields, so zero and `false` remain distinct from unavailable data. The snapshot
includes price, VWAP/distance, day change, watched-symbol relative rank,
security/halt and borrow state, available fundamentals, session phase, current
bar/cumulative/AE volume evidence, and available session/structural levels.

`context_as_of_ts_ms` records the latest normalized quote time used and may be
later than the bar's start timestamp because a completed bar is evaluated when
the following stream update closes it. Missing fundamentals or levels remain
explicitly unavailable. The snapshot is journal evidence only and is not passed
to detectors or used as a gate.

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

### Volume-primitive contract

The shared structure layer provides completed-bar volume extraction, recent
mean/median, generic segment-to-baseline contraction ratio, current-bar expansion
ratio, and least-squares volume trend. Invalid or absent observations are
unavailable; recorded zero volume remains zero. Trigger context exposes the
20-bar recent statistics, current expansion, and trend as evidence. No detector
calls these values and no volume threshold gates a setup.

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

### Session-level primitive contract

The shared structure layer now provides a schema-version-1 session context for
premarket high/low, regular-session HOD/LOD, opening-range high/low, prior-day
regular-session high/low/close, and VWAP. The default opening range is an
explicit 10-minute `SessionLevelConfig` value. The result records its timezone,
session date, as-of timestamp, configured duration, and whether the opening
range clock has completed.

Callers may supply their canonical live VWAP; otherwise the primitive calculates
VWAP only from available positive-volume bars. Prior-day values remain
unavailable unless an earlier regular session is present in the supplied bars.
Distances are percentage points from current price to each available level.
Trigger snapshots expose these standardized values as evidence while retaining
the existing AE open price. No detector consumes these primitives in this phase.

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

### Overlap-analysis contract

`pattern_overlaps.json` schema version 1 is derived from the first-class pattern
journal and can be regenerated without modifying raw recordings. Cross-detector
instances overlap only during a conservative observed lifetime: from the first
journal observation through the first explicit invalidation, or through one
known evaluation cadence after the final journal observation. When cadence is
unknown, no time is added. The report never infers continued activity from a
detector's silence.

Each record includes both pattern IDs/types, observed and formation timestamps,
overlap bounds, trigger times, triggers that occurred inside the other observed
lifetime, and structural-level comparisons. Level comparisons retain exact
percentage-point distance and use an explicit, configurable 1% research
tolerance for the `nearby` marker. This tolerance does not affect detectors or
trade qualification. Reports include aggregate counts by pattern-type pair and
are available read-only at
`GET /api/evaluation/pattern-overlaps/{session_id}` with optional `symbol` and
`level_tolerance_pct` query filters.

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
