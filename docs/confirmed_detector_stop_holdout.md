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

The additive, outcome-blind date registry is
`docs/prospective_holdout_dates.json`. It was recorded before prospective
outcomes were inspected. September 30 is permanently marked
`excluded_partial_capture` because authorization and deployment interrupted the
capture. It contributes no trading date, opportunity, paired-trade, or
performance count; its raw recordings and research evidence remain preserved.
October 1 is pending until its completed capture can be checked. Pending and
excluded dates never enter progress counts.

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

These are exactly the primary readiness requirements. Momentum-eligible trade
count is reported separately and never blocks primary readiness. The momentum
policy remains preregistered but exploratory: report its eligible/traded counts,
outcomes, and paired decomposition, but it cannot be approved from this holdout
regardless of apparent results. Do not select a momentum sample threshold from
historical results. Preregister a separate prospective validation after its
natural eligibility frequency is known.

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

Momentum eligibility outcomes still report net and average R; losing less is
not positive expectancy. Its locked constants are 8.0% minimum
breakout room, 10.0% preferred room, and 2.0 time-adjusted RVOL. Resistance is
limited to registered causal local/session levels (including PMH, ORH, regular
high, VWAP, and nearest resistance); incomplete evidence is unavailable.

There is no authoritative multi-session RVOL field in the engine. The existing
`volume_multiple` is a one-minute spike measure and is not used. Current-session
volume comes from Schwab Level One field 8 (`total_volume`, normalized as
`QuoteEvent.volume`). Prior-session evidence comes from persisted Level One
recordings or Schwab `PRICEHISTORY` one-minute candle volume with extended
hours requested and phase volume summed causally. RVOL is current cumulative
phase volume divided by the median at the identical premarket/RTH-relative
timestamp over the previous 20 eligible same-symbol sessions. Recorded Level
One RTH volume subtracts the last pre-09:30 total.
History is deduplicated by symbol, distinct ET trading date, and market phase,
so multiple recording sessions on one date count once. Missing history is
unavailable; current/future sessions and post-decision data are excluded.

## Prerequisite evidence collection

Run the read-only retention canary independently from an authenticated app
environment. Its cutoff is exclusive, and it rejects out-of-bounds candles
even when the upstream response includes them:

```bash
python -m momentum_companion.evaluation.schwab_retention_canary \
  /tmp/schwab-retention-canary.json \
  --symbols APUS,IMCC,NCPL,BENF,JAGX \
  --cutoff-date 2026-09-29 \
  --calendar-days 50
```

The enrollment sidecar is additive and research-only. Enable it explicitly;
without this setting the normal runtime is unchanged:

```bash
export TOS_RVOL_EVIDENCE_DIR=/data/research/rvol-evidence
```

At first recording enrollment it requests prior one-minute extended-hours
history and atomically stores at least 20 complete previous sessions when
available. The sidecar contains raw extended-hours candles, separate
premarket/RTH/after-hours cumulative series, request bounds, receipt time,
source, and coverage diagnostics. The decision date is excluded, requests are
serialized and rate-limited, complete evidence is cached, and an incomplete
response cannot overwrite complete evidence.

Future trigger journals also persist the causal resistance candidates evaluated
at the timestamp: PMH, ORH, regular-session high, VWAP, prior-day high,
local/micro resistance, swing highs, detector structural resistance, and the
selected nearest overhead level. Each candidate records availability, as-of
time, entry distance, and whether it is overhead. Completeness is false unless
all required sources were evaluated and available. A broken breakout level is
tagged and cannot automatically become the next overhead level. Wrapped and
legacy `nearest_resistance` schemas remain readable.

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
    --code-revision "${REVISION}" \
    --rvol-evidence-dir /data/research/rvol-evidence
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

## Outcome-blind collection progress

Do not run the outcome-bearing evaluator above while the sample is accumulating.
The collection-progress command accepts only an outcome-blind inventory and
rejects outcome keys such as wins, losses, exits, realized R, MFE, MAE, and
expectancy. Its output is limited to date status, grouped and paired counts,
momentum evidence/eligibility counts, minimum-size progress, and completeness
warnings:

```bash
cd /srv/apps/ToS_Companion
docker run --rm --user 0:0 \
  -w /workspace \
  -e PYTHONPATH=/workspace/src \
  -v deploy_tos-companion-data:/data:ro \
  -v /srv/apps/ToS_Companion:/workspace:ro \
  deploy-tos-companion \
  python -m momentum_companion.evaluation.holdout_progress \
    progress /workspace/docs/prospective_holdout_dates.json \
    --rvol-evidence-dir /data/research/rvol-evidence
```

An optional inventory must contain only `trading_date`, `opportunity_id`,
`baseline_entered`, `confirmed_entered`, `momentum_evidence`, and
`momentum_eligibility` (`trade_candidate`, `preferred_candidate`,
`monitor_only`, or `unavailable`). Duplicate opportunity IDs are deduplicated
within an exact trading date, not across dates.

At end of day, validate October 1 capture continuity without calculating or
displaying any trade outcome:

```bash
cd /srv/apps/ToS_Companion
docker run --rm --user 0:0 \
  -w /workspace \
  -e PYTHONPATH=/workspace/src \
  -v deploy_tos-companion-data:/data:ro \
  -v /srv/apps/ToS_Companion:/workspace:ro \
  deploy-tos-companion \
  python -m momentum_companion.evaluation.holdout_progress \
    audit-date /data/recordings --date 2026-10-01
```

The date can be changed from `pending` only after this audit is reviewed. It is
eligible only with continuous recording coverage from 07:00 through at least
10:30 ET, no material interval over 60 seconds between recording sessions, and
no unresolved market-data gap. Multiple sessions may be combined only when
they satisfy that rule. A failed date remains preserved and receives a specific
exclusion reason in the date manifest.

## Trade Review preview

```bash
cd /srv/apps/ToS_Companion
export TOS_RESEARCH_OUTPUT_DIR=/tmp/tos-counterfactual-a
PYTHONPATH=src .venv/bin/python -m momentum_companion.web
```

Select **Trade Review**. A missing directory or results file shows an empty
state and leaves the normal application unchanged.
