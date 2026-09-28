# Trade simulation v1

Trade simulation is a deterministic evaluation layer over recorded pattern journals and recorded Schwab Level 1 evidence. It does not alter detector semantics, replay behavior, or live setup gating.

## Endpoint

`GET /api/evaluation/trade-simulation/{session_id}`

Optional query:

- `symbol=XYZ`

The response contains the frozen policy, every consolidated candidate, simulated trades, skipped candidates, data-quality blocks, and summary statistics.

## Frozen v1 execution contract

The defaults are intentionally explicit and conservative:

- Trigger source: first `BREAKOUT` or `CONTINUATION` observation for each pattern instance.
- Signal consolidation: triggers on the same symbol are merged when they occur within 15 seconds of the candidate's first trigger. The contributing detector IDs/types are retained; chained triggers outside that fixed window do not extend the candidate.
- Entry: first complete recorded L1 quote at or after the observable trigger, within 10 seconds.
- Long entry price: recorded ask.
- Stop: closest detector-supported invalidation level below the entry. A Tight Consolidation Breakout may use `evidence.breakdown_level`.
- Missing stop: keep the candidate for diagnostics, but do not score it as a simulated trade.
- Target: 2R, where `R = entry - stop`.
- Long exit price: recorded bid.
- Exit ordering: first recorded bid to touch/cross stop or target wins. Otherwise exit on the last recorded bid at or before the 15-minute timeout.
- Cooldown: at least 120 seconds from an accepted candidate trigger, and never shorter than the simulated position's lifetime. Later candidates during cooldown or while that position is open are not separate simulated trades.
- Position sizing: normalized 1R only. No account size or share count is assumed.
- Slippage: v1 uses the actual recorded ask for entry and bid for exit. Additional configurable stop/target slippage defaults to 0 bps.
- Spread: entry spread and spread percentage are recorded.
- MAE/MFE: measured from the recorded L1 bid path through the simulated exit.
- Data quality: an unresolved gap, explicit halt/suspension, or end-of-recording boundary blocks scoring if it occurs before an otherwise determined exit.

## Interpretation

This module is an execution-policy research tool, not evidence that a detector has positive expectancy. Detector thresholds remain unchanged. The simulator policy should be versioned and held fixed while evaluating reserved recordings; changing policy after reviewing a recording makes that recording development evidence for the new policy.

The output deliberately retains skipped/no-stop candidates and blocked intervals so unfavorable or incomplete evidence is not silently discarded.
