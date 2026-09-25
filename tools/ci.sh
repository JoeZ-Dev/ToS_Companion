#!/usr/bin/env bash
set -euo pipefail

# Linux core validation for the current browser/server architecture.
# Historical desktop/Qt/auth-contract tests remain in the repository for
# reference but are not a release gate for this branch because they target
# retired interfaces and semantics.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Running maintained core test set..."
pytest -q \
  tests/test_ae.py \
  tests/test_app_state.py \
  tests/test_bar_aggregator.py \
  tests/test_bar_session.py \
  tests/test_codex_bridge_client.py \
  tests/test_companion_runtime.py \
  tests/test_companion_session.py \
  tests/test_emm_abort.py \
  tests/test_emm_engine.py \
  tests/test_gate_block.py \
  tests/test_gates.py \
  tests/test_indicators.py \
  tests/test_journal_writer.py \
  tests/test_llm_coach_validation.py \
  tests/test_llm_normalization.py \
  tests/test_llm_response_normalization.py \
  tests/test_llm_schema_repair.py \
  tests/test_llm_service.py \
  tests/test_llm_validator.py \
  tests/test_market_day_recorder.py \
  tests/test_massive_fundamentals_client.py \
  tests/test_momentum_context.py \
  tests/test_nearest_resistance_fallback_helper.py \
  tests/test_normalization_extra_fields.py \
  tests/test_pattern_engine.py \
  tests/test_pattern_replay.py \
  tests/test_pattern_service.py \
  tests/test_snapshot_status_summary.py \
  tests/test_stream_freshness.py \
  tests/test_stream_mapping.py \
  tests/test_stream_raw_recording.py \
  tests/test_synthetic_trigger.py \
  tests/test_trade_executor_cancel.py \
  tests/test_trade_executor_integration.py \
  tests/test_vwap.py \
  tests/test_web_app.py

echo "Linux core validation complete."
