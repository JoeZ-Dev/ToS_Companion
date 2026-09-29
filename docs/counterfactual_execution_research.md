# Offline counterfactual execution research

This module compares six fixed execution policies across all 893
production-cooldown-grouped opportunities from September 23, 24, 25, and 28.
It is an exploratory historical comparison, not validation. It neither changes
production detectors nor selects a policy solely from aggregate net R.

The constants are centralized in `CounterfactualConfig` and emitted verbatim in
`policy-definitions.json`. The fixed matrix uses the current production entry
and detector stop, completed-bar confirmation with the detector's own breakout
or continuation level, causal structural stops, breakout retest and hold,
1.5 times the median true range of the preceding twelve completed 10-second
bars (with an 8% risk cap), and at most one renewed-confirmation re-entry.
Every target is fixed at 2R and every leg retains the existing 15-minute
horizon. Entries execute against historical ask; stops, targets, and timeouts
execute against historical bid. Existing stop/target slippage remains zero bps.

Human labels are a diagnostic join only. `clear`, `uncertain`, and `rejected`
remain separate and never affect an entry, stop, exit, or recommendation. The
tool refuses to infer item-level labels from aggregate counts; an empty or
partial label file is reported explicitly.

## Exact reproduction

Generate or reuse the locked replay overlay from the blinded review revision,
then run two complete output trees with the recordings, baseline overlay,
review pack, and checkout mounted read-only:

```bash
REVISION="$(git -C /srv/apps/ToS_Companion rev-parse HEAD)"
mkdir -p /tmp/tos-counterfactual-a /tmp/tos-counterfactual-b

for OUTPUT in /tmp/tos-counterfactual-a /tmp/tos-counterfactual-b; do
  docker run --rm --user 0:0 \
    -w /workspace \
    -e PYTHONPATH=/workspace/src \
    -v deploy_tos-companion-data:/data:ro \
    -v /srv/apps/ToS_Companion:/workspace:ro \
    -v /tmp/tos-replay-final-a.89jl1q/overlays/inclusive_exploratory:/baseline:ro \
    -v /tmp/tos-opportunity-final-a.YSSp6o:/review:ro \
    -v /tmp/locked-opportunity-labels.csv:/labels.csv:ro \
    -v "${OUTPUT}:/output" \
    deploy-tos-companion \
    python -m momentum_companion.evaluation.counterfactual_execution \
      /data/recordings /baseline /output \
      --code-revision "${REVISION}" \
      --review-manifest /review/review-manifest.json \
      --labels-csv /labels.csv
done

diff -qr /tmp/tos-counterfactual-a /tmp/tos-counterfactual-b
sha256sum /tmp/tos-counterfactual-a/*
```

The five deliverables are `counterfactual-results.json`,
`counterfactual-trades.csv`, `counterfactual-summary.md`,
`policy-definitions.json`, and `artifact-hashes.json`. Capture hashes are taken
before and after the run and serialized into both the results and hash manifest.
