# Blinded opportunity review export

`momentum_companion.evaluation.opportunity_review` builds an offline review pack
from the inclusive September 23–25 current-code replay overlays and the
September 28 persisted live journal. It does not change detector, simulator, or
live-runtime behavior.

The export uses `production_cooldown_grouping`: every simulator candidate that
is not suppressed by production cooldown starts an opportunity, and subsequent
`SKIPPED_COOLDOWN` candidates remain attached as repeated signals. This is an
audit boundary, not a claim that each group is a perfect market-opportunity
cluster.

Sampling uses the fixed seed `tos-opportunity-review-v1`. It balances trading
dates and greedily adds uncovered symbol/day, pattern, time-of-day,
single/multi-pattern, and repeat-density strata. It never reads return, MFE,
MAE, exit, win/loss, or later-direction fields. Controls are active recorded
points with no raw trigger or simulator candidate during the preceding
production cooldown interval.

Every chart requests the same 20-minute pre-review window. A no-history
`ReplayEngine` processes recorded events only through the review timestamp, and
the existing review packet interface supplies 10-second OHLCV, causal VWAP,
quote, and replay quality evidence. Capture-boundary truncation is explicit.

The output contains:

- `blinded/triggered/*.png` and `blinded/controls/*.png`: opaque filenames and
  1600x900 trigger-bounded charts;
- `blinded-review-pack.pdf`: the same 60 blinded windows in one document;
- `review-manifest.json`: blinded chart data, provenance class, quote, and paths;
- `machine-evidence.json`: pattern names, contributors, levels, and stop bases;
- `restricted/outcomes.json`: post-review evidence, kept outside blinded paths;
- `labels.csv`: the empty review form;
- `opportunity-audit.json`: grouping and repeated-signal distributions;
- `artifact-hashes.json` and `source-integrity.json`: reproducibility evidence.

Generate the required replay overlays first, then the review pack. Mount both
the capture volume and checkout read-only:

```bash
mkdir -p /tmp/tos-replay-baseline /tmp/tos-opportunity-review

docker run --rm --user 0:0 \
  -w /workspace \
  -e PYTHONPATH=/workspace/src \
  -v deploy_tos-companion-data:/data:ro \
  -v /srv/apps/ToS_Companion:/workspace:ro \
  -v /tmp/tos-replay-baseline:/baseline \
  deploy-tos-companion \
  python -m momentum_companion.evaluation.replay_trade_baseline \
    /data/recordings /baseline \
    --code-revision "$(git -C /srv/apps/ToS_Companion rev-parse HEAD)" \
    --start-date 2026-09-22 \
    --end-date 2026-09-25

docker run --rm --user 0:0 \
  -w /workspace \
  -e PYTHONPATH=/workspace/src \
  -v deploy_tos-companion-data:/data:ro \
  -v /srv/apps/ToS_Companion:/workspace:ro \
  -v /tmp/tos-replay-baseline:/baseline:ro \
  -v /tmp/tos-opportunity-review:/review \
  deploy-tos-companion \
  python -m momentum_companion.evaluation.opportunity_review \
    /data/recordings \
    /baseline/overlays/inclusive_exploratory \
    /review \
    --code-revision "$(git -C /srv/apps/ToS_Companion rev-parse HEAD)" \
    --seed tos-opportunity-review-v1
```

Do not open `restricted/outcomes.json` until validity labels are locked.
