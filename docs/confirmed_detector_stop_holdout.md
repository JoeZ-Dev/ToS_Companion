# Prospective holdout protocol: confirmed detector stop and momentum eligibility

Status: locked before unseen-data evaluation. This protocol does not authorize
deployment and does not modify either policy.

## Scope and eligibility

Evaluate `production_baseline`, `confirmed_detector_stop`, and the newly
preregistered `confirmed_detector_stop_momentum_eligible` independently. The
original baseline-versus-confirmed comparison remains visible and unchanged;
momentum eligibility is only a selection layer over the unchanged confirmed
trade. A capture is eligible only when its
America/New_York trading date is strictly after September 29, 2026. September
29 and every earlier date are excluded. The command requires the literal cutoff
`2026-09-29`; it has no default and refuses a different value.

This amendment was locked after a read-only catalog scan confirmed no evaluable
post-cutoff capture existed. Do not tune constants, alter confirmation or stop behavior, add policies, or
select a policy while this holdout is accumulating. If evidence motivates a
change, close the holdout, classify all inspected data as development data,
freeze a new protocol, and collect a new unseen corpus.

Human chart labels may be added after primary results are locked, but only as a
secondary diagnostic. They cannot change entries, eligibility, stops, exits,
success criteria, or policy selection.

## Minimum size

Do not make the locked assessment until all three minimums are reached:

- 20 independent trading dates;
- 500 production-cooldown-grouped opportunities; and
- 250 opportunities traded by both policies.

Trading dates, not trades, are the primary independent units because intraday
opportunities share market regime and symbol conditions. Twenty dates provide
multiple weekly regimes; 500 opportunities provide useful date/symbol
subgroups; 250 paired trades keep the execution comparison from being driven by
a small paired subset. These are prospective design requirements, not values
optimized against the September historical results. Do not stop early after a
favorable interim result.

The momentum policy uses the same 20 dates and 500 opportunities and requires
at least 250 eligible trades before assessment.

## Locked reporting

Report the following without tuning or choosing between policies:

1. Aggregate net R, average R, trade count, win rate, losses, and timeouts for
   all three policies independently.
2. Both-traded paired mean R delta (`confirmed - baseline`), paired policy net
   and average R, and confirmed-better/baseline-better/equal counts.
3. Baseline-only and confirmed-only counts and net R. Report the selection
   effect separately as `confirmed-only net R - baseline-only net R`.
4. Reconcile aggregate policy difference as selection effect plus both-traded
   execution effect.
5. Repeat policy and paired results by independent trading date and symbol.

Success requires confirmed entry to have positive out-of-sample net R and
positive average R. Merely losing less than baseline is not success. It must
also avoid materially degrading shared-trade execution: the locked
both-traded paired mean delta must be at least `-0.10R`. This non-inferiority
floor is an evaluation guardrail fixed before unseen results, not a trading
threshold. Passing the protocol makes the policy eligible for a separate
decision review; it does not approve deployment.

Momentum eligibility separately requires positive out-of-sample net R and
average R. Losing less is not success. Its locked constants are 8.0% minimum
breakout room, 10.0% preferred room, and 2.0 time-adjusted RVOL. Resistance is
limited to registered causal local/session levels (including PMH, ORH, regular
high, VWAP, and nearest resistance); incomplete evidence is unavailable.

There is no authoritative multi-session RVOL field in the engine. The existing
`volume_multiple` is a one-minute spike measure and is not used. RVOL derives
from Schwab Level One field 8 (`total_volume`, normalized as
`QuoteEvent.volume`): cumulative phase volume at decision time divided by the
median at the identical premarket/RTH-relative timestamp over the previous 20
eligible same-symbol sessions. RTH volume subtracts the last pre-09:30 total.
Missing history is unavailable; current/future sessions and post-decision data
are excluded.

## Exact command

After enough post-cutoff captures with persisted pattern journals exist:

```bash
REVISION="$(git -C /srv/apps/ToS_Companion rev-parse HEAD)"
mkdir -p /tmp/tos-confirmed-holdout

docker run --rm --user 0:0 \
  -w /workspace \
  -e PYTHONPATH=/workspace/src \
  -v deploy_tos-companion-data:/data:ro \
  -v /srv/apps/ToS_Companion:/workspace:ro \
  -v /tmp/tos-confirmed-holdout:/output \
  deploy-tos-companion \
  python -m momentum_companion.evaluation.prospective_holdout \
    /data/recordings /output \
    --cutoff-date 2026-09-29 \
    --code-revision "${REVISION}"
```

To reproduce determinism, run the same command into two empty output
directories and compare them:

```bash
diff -qr /tmp/tos-confirmed-holdout-a /tmp/tos-confirmed-holdout-b
sha256sum /tmp/tos-confirmed-holdout-a/*
```

The evaluator writes `holdout-results.json`, `holdout-trades.csv`,
`holdout-summary.md`, and `artifact-hashes.json`. It hashes eligible source
captures before and after evaluation and fails if any source bytes change.

## Trade Review preview

```bash
cd /srv/apps/ToS_Companion
export TOS_RESEARCH_OUTPUT_DIR=/tmp/tos-counterfactual-a
PYTHONPATH=src .venv/bin/python -m momentum_companion.web
```

Select **Trade Review**. A missing directory or results file shows an empty
state and leaves the normal application unchanged.
