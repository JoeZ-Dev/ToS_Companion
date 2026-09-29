# Execution Intelligence Engine

## Purpose

The Execution Intelligence Engine (EIE) is a separate real-time layer between a valid trade plan and the existing order executor.

It does **not** decide whether a chart setup is valid. The setup engine owns that.

It answers a narrower question:

> Given that we intend to trade, what is the market doing in the seconds around entry, while in the position, and near the planned exit?

## Architectural boundary

```text
Market data
   |
   +--> Setup / Pattern Engine --> Trade Plan
   |                               entry / stop / target
   |
   +--> Execution Intelligence Engine
                                   |
                                   v
                          execution recommendation
                                   |
                                   v
                         existing execution layer
```

Existing execution code remains responsible for broker/order mechanics. EIE supplies evidence and state; it does not bypass risk gates.

## Initial states

Keep the state space intentionally small:

- `NEUTRAL` — no material microstructure edge.
- `ENTRY_SUPPORTIVE` — immediate order flow supports the planned entry.
- `ENTRY_DETERIORATING` — entry conditions are worsening; delay/cancel evidence.
- `HOLD_SUPPORTIVE` — current position remains supported.
- `EXIT_PRESSURE` — near-term evidence favors defensive exit.
- `CONTINUATION_SUPPORTIVE` — target is being approached/reached with evidence that continuation may persist.

These are observations, not automatic orders in the foundation phase.

## Inputs

The engine should consume normalized microstructure observations rather than broker-specific payloads.

Initial feature families:

1. **Top of book / spread**
   - bid, ask, spread
   - bid/ask size
   - spread widening/narrowing
   - bid/ask stepping

2. **Depth / Level 2**
   - depth in the nearest N levels
   - depth imbalance
   - depletion rate
   - replenishment rate
   - unusually large displayed liquidity
   - repeated replenishment / absorption evidence

3. **Time & sales / tape**
   - trade rate
   - share rate
   - estimated aggressive-buy vs aggressive-sell volume
   - price progress per unit volume
   - short-window acceleration/deceleration

4. **Trade-plan context**
   - intended entry
   - actual fill
   - stop
   - target
   - current position state

## Latency requirement

EIE is not an LLM loop.

Feature/state updates should be local and deterministic, designed for sub-second processing. LLM analysis may consume logged EIE state asynchronously for research, explanation, or strategy review, but must not be required for immediate entry/exit decisions.

## Complexity / tuning guardrails

The engine must not become a pile of independent magic thresholds.

Rules:

- Separate **measurements** from **policy**.
- Prefer normalized features (ratios, rates, z-scores/relative baselines) over raw share-count thresholds.
- Keep a small public state vocabulary.
- Every feature used in policy must be replayable and logged.
- New features do not become decision gates until evaluated out-of-sample.
- Version policy separately from feature extraction.
- Avoid symbol-specific tuning unless explicitly tested as a separate model.
- Do not let EIE redefine setup validity, entry price, stop, or target.

## Replay requirement

For trustworthy tuning, recordings must preserve the source data needed to reconstruct EIE features causally.

Current replay/recording infrastructure is reusable, but historical captures centered on L1/10-second bars are not sufficient for full EIE evaluation. New captures should preserve Level 2 and time-and-sales events with timestamps and ordering adequate for sub-second replay.

## Phase plan

### Phase 1 — foundation
- define normalized contracts
- define small state vocabulary
- keep engine advisory only
- identify Schwab L2/time-and-sales feeds and recording requirements

### Phase 2 — feature extraction
- spread / top-of-book features
- depth imbalance/depletion/replenishment
- tape aggression / velocity
- short rolling windows (for example 250 ms, 1 s, 3 s)

### Phase 3 — replay evaluation
- reconstruct features causally
- align EIE state to simulated entries, exits, MFE/MAE
- measure whether EIE observations improve outcomes over the same trade plans

### Phase 4 — execution policy
Only after out-of-sample evidence:
- entry delay/cancel policy
- early defensive exit policy
- target continuation policy

## Success criterion

EIE succeeds only if the same pre-existing trade plans produce better out-of-sample execution outcomes after realistic spread/slippage assumptions. More complexity by itself is not success.
