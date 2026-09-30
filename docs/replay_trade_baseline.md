# Exploratory current-code replay trade baseline

`momentum_companion.evaluation.replay_trade_baseline` evaluates legacy captures
that predate the persisted pattern journal. It keeps these results separate from
the September 28 persisted-journal baseline.

The adapter uses `ReplayEngine` and the current production detector registry.
It disables post-recording historical seeding, builds temporary journal rows
with `build_pattern_event`, applies the same snapshot-transition deduplication
as `PatternEventJournal`, and invokes the unchanged production trade simulator.
Original recording directories are read-only inputs. Generated manifests,
journals, symlinks, simulations, and reports live under the requested output
directory.

Every exploratory result is marked as `replay_current_code`, with unavailable
status evidence and partial context. The three views are fixed sensitivity
screens, not strategy alternatives:

- `inclusive_exploratory`: all causal current-code triggers.
- `conservative_inactivity_exclusion`: excludes merged candidates whose trigger
  occurs during the five minutes after a per-symbol L1 inactivity interval of
  at least 60 seconds.
- `strict_data_quality_exclusion`: also excludes merged candidates whose
  contributing formation spans a gap,
  production-simulator data-quality failures, and incomplete full paths.

Run from the research revision with the capture volume and source checkout
mounted read-only:

```bash
mkdir -p /tmp/tos-replay-baseline
docker run --rm --user 0:0 \
  -w /workspace \
  -e PYTHONPATH=/workspace/src \
  -v deploy_tos-companion-data:/data:ro \
  -v /srv/apps/ToS_Companion:/workspace:ro \
  -v /tmp/tos-replay-baseline:/output \
  deploy-tos-companion \
  python -m momentum_companion.evaluation.replay_trade_baseline \
    /data/recordings \
    /output \
    --code-revision "$(git -C /srv/apps/ToS_Companion rev-parse HEAD)" \
    --start-date 2026-09-22 \
    --end-date 2026-09-25
```

The main report is `/tmp/tos-replay-baseline/replay-trade-baseline.json`.
