# Momentum context foundation

This layer adds market context around the registered pattern engine without turning context into an entry signal.

## Halt awareness

Schwab `LEVELONE_EQUITIES` field 32 (`Security Status`) is subscribed and preserved in the canonical quote as `security_status`.

Expected values include `Normal`, `Halted`, and `Closed`.

The live runtime and replay engine feed status changes into `PatternEvaluationService`. Pattern evidence carries:

- current trading status
- `halted_since_ms`
- `last_halt_start_ms`
- `last_resume_ms`

A halt is therefore distinct from a quiet period or missing stream data. The 10-second aggregator does not forward-fill missing bars.

## Borrow context

The L1 subscription also requests:

- 46 HTB quantity
- 47 HTB rate
- 48 hard-to-borrow
- 49 shortable

These are context fields only. They are not treated as bullish/bearish signals by themselves.

## Relative strength

Cross-watchlist relative strength uses current last price versus Schwab's previous-close field. Watched symbols are ranked by session percent change.

This answers "which watched name is leading right now?" It is intentionally not RSI and is not yet sector/benchmark-relative strength.

## Adaptive confirmation

`setup_engine/confirmation.py` confirms price acceptance by real elapsed time rather than a fixed number of bars.

The required hold is:

`clamp(formation_duration * formation_fraction, min_seconds, max_seconds)`

This means a fast-forming setup can confirm faster than a slow-forming setup. Genuine data gaps break the current confirmation streak.

Current pattern use:

- Ascending triangle breakout
- Micro-pullback continuation

The current pattern engine evaluates completed 10-second bars, so practical confirmation resolution is still bounded by that cadence even when the configured minimum is lower.

## MAE / MFE

`analysis/excursions.py` provides reusable long-trade excursion measurements:

- MAE: lowest adverse move from entry
- MFE: highest favorable move from entry

The utility accepts an entry/exit evidence window and returns both percent excursion and the price/timestamp where each extreme occurred. It is intended for replay/backtest evaluation and does not create trades.

## Float

Float size is deliberately not synthesized. The current Schwab L1 contract does not provide a trustworthy float field. A later implementation should add float only when a defensible source and timestamp/provenance contract are defined.
