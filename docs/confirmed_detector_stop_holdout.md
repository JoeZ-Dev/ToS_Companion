# Prospective holdout protocol: confirmed detector stop

Status: locked before unseen-data evaluation. This protocol does not authorize
deployment and does not modify either policy.

## Scope and eligibility

Evaluate `production_baseline` and `confirmed_detector_stop` side by side using
the frozen counterfactual implementation. A capture is eligible only when its
America/New_York trading date is strictly after September 29, 2026. September
29 and every earlier date are excluded. The command requires the literal cutoff
`2026-09-29`; it has no default and refuses a different value.

Do not tune constants, alter confirmation or stop behavior, add policies, or
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

## Locked reporting

Report the following without tuning or choosing between policies:

1. Aggregate net R, average R, trade count, win rate, losses, and timeouts for
   both policies.
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
