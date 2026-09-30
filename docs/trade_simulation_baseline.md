# Multi-session trade-simulation baseline

`momentum_companion.evaluation.batch_trade_simulation` is a deterministic batch
wrapper around the production schema-v2 `build_trade_simulation` function. It
does not implement a second simulator or change any execution-policy setting.

The report includes the complete recording inventory, explicit eligibility and
exclusion reasons, per-session production output, aggregate/day/symbol-day
policy summaries, data-quality totals, independence/concentration diagnostics,
and raw simulated trade records. Wall-clock generation fields are omitted so
the same revision, corpus, and configuration produce byte-identical JSON.

For the joelab Docker volume, run the branch source against a read-only capture
mount. The container runs as UID 0 only because the repository's evaluation
package directory is not readable by the image's `companion` user; the capture
volume remains read-only.

```bash
mkdir -p /tmp/tos-companion-baseline
docker run --rm --user 0:0 \
  -w /workspace \
  -e PYTHONPATH=/workspace/src \
  -v deploy_tos-companion-data:/data:ro \
  -v /srv/apps/ToS_Companion:/workspace:ro \
  -v /tmp/tos-companion-baseline:/output \
  deploy-tos-companion \
  python -m momentum_companion.evaluation.batch_trade_simulation \
    /data/recordings \
    --code-revision "$(git -C /srv/apps/ToS_Companion rev-parse HEAD)" \
    --output /output/trade-simulation-baseline.json
```

The source checkout and capture volume are both mounted read-only. The only
writable mount is the output directory.
