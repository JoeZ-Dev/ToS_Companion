Project Summary
---------------
Momentum Trading Companion MVP per docs/specs.md: Windows-targeted Python desktop app (PySide6 + Lightweight Charts) that streams Schwab equities data, builds 10s bars + studies (VWAP/EMA/MACD), runs deterministic Analysis Engine snapshots, provides optional LLM coaching, executes long-only trades with EMM and synthetic stops, and journals all activity in per-instance SQLite.

Completed Work
--------------
- Baseline scaffolding: src package layout with module stubs for §13 components (clients, aggregator, indicators, execution, triggers, journal, state, UI, LLM).
- requirements.txt created with spec-aligned dependencies.
- pyproject.toml added for packaging/pytest config.
- Path helpers per §7 (platformdirs) and schema initialization with v1 DDL per specs.md §7.2.
- Added canonical data contracts (LLM payload/output, quote event reason codes) and Appendix D stream mapping with tests.
- Initial test harness (`tests/conftest.py`, `tests/test_stream_mapping.py`) passing via `pytest -q`.
- Journal contracts and writer with CSV/JSON export and tests.
- Implemented basic SchwabStreamClient wrapper using stream mapping cache; logging tuned; tests still passing.
- SchwabRestClient scaffolded; AppStateStore implemented with tests.
- BarAggregator10s enhanced with volume delta handling, anomaly capping, and tests passing.
- Added simple backoff decorator and reconciliation helper skeleton; stream client tracks last_ts_ms.
- EMMEngine and TradeExecutor skeletons implemented.
- VWAP computation helper added (skips tests if pandas unavailable in current env).
- Added canonical checklist and status file.
- TradeExecutor cancel/flatten journaling; reconcile helper; stream freshness check; placeholder error mapping.
- LLMCoach reason code validation added; acceptance/build stubs in place.
- LLMService normalizes snapshot and validates coach responses.
- Trading gate evaluation helper ties auth/stream/journal/reconciliation/freshness.
- TokenProvider now refreshes via Schwab token endpoint with singleflight, atomic write, and triggers AUTH_REQUIRED state on failure.
- Stream client restarts on token refresh, reconnects with backoff, journals STREAM_DOWN, and resubscribes after LOGIN.
- EMM engine implements abort reasons (NO_QUOTE/STALE_QUOTE/TIMEOUT/DISCONNECT) with journaling; tick rounding and tests in place.
- UI scaffold updated with state callbacks; state wiring from token/auth, stream down, LLM invalid output, and reconciliation gate.
- LLMService now includes flash-delta detection per specs §11.4 with callback hook and tests.
- CI helper scripts added: tools/ci.sh (pytest) and tools/windows_smoke.ps1 (PyInstaller + mock run).
- Auth Helper added (tools/auth_helper) serving access tokens from homelab; TokenProvider supports AUTH_HELPER_URL mode with AUTH_REQUIRED fallback; tests stub helper mode.
- Upgraded charting to Lightweight Charts v5.1.0 with volume overlaid on price, MACD pane (line/signal/hist), and VWAP/EMA overlays via QtWebEngine widget.
- IndicatorsEngine now computes MACD line/signal/hist alongside VWAP/EMA; controller pushes MACD to chart.

Remaining Work
--------------
- LLMCoach invocation remains minimal; flash-delta detection and full UI behaviors still needed.
- Indicators/chart polish and full TradeExecutor reconciliation still pending.
- CI now wired: .github/workflows/ci.yml runs pytest on Linux and PyInstaller smoke on Windows via tools/windows_smoke.ps1.

Authoritative Checklist (execute in order)
------------------------------------------
1) Repository bootstrap: python packaging scaffolding, lint/test config, platformdirs paths, logging skeleton.
2) Data contracts: TypedDict/dataclasses for canonical quote events (§13.1), AE snapshot input/output (§11.2.5, analysis_engine.md), LLM request/response schemas (§11.3), Schwab REST/stream normalization.
3) Storage: SQLite schema v1 creation per specs.md §7.2; app_state helpers; per-instance path handling.
4) OAuth/token handling: Schwab auth flow, DPAPI at-rest encryption, token refresh, oauth.lock enforcement.
5) SchwabRestClient: accounts/orders/history/quotes with retries/backoff, error mapping, reconciliation fetch.
6) SchwabStreamClient: WebSocket login + LEVELONE_EQUITIES subscription, Appendix D field mapping, reconnect logic, quote freshness tracking.
7) BarAggregator10s: 10s bars left-inclusive/right-exclusive, gap handling, volume delta logic, stale flagging and styling hook.
8) IndicatorsEngine: VWAP (anchored 04:00 ET), EMA9/EMA20 visibility rules; reuse AE outputs when applicable.
9) Analysis Engine integration: invoke AE-1.1 snapshot per completed 10s bar; handle data_quality/status gates; store AE-1.0 profiles.
10) UIController (PySide6 + Lightweight Charts): layout per §4.1; chart behaviors; trade ticket; LLM panel; flash notifications.
11) TradeExecutor: NORMAL vs SEAMLESS order routing, EMMEngine chase-limit loop, synthetic stop/trigger arming, flatten/cancel flows.
12) SyntheticTriggerEngine: arm/disarm/firing logic with session rules and reconnect handling.
13) JournalWriter: append-only writes, verification_degraded handling, export to CSV/JSON, required event coverage.
14) LLM Coach integration: gating on status/data_quality, prompt versioning/logging, schema validation, flash-worthy deltas, Transfer behavior.
15) Hotkeys/options persistence: toggles, geometry/studies persistence, app_state storage.
16) Acceptance tests/smoke: unit tests per modules; trading gate startup conditions; journal export; build/run scripts; Windows packaging (PyInstaller).

Known Blockers / Clarifications
-------------------------------
- Remaining TODOs:
  - EMMEngine submit/replace integration with REST.
  - LLMCoach actual invocation and schema validation beyond reason_codes.
  - TradeExecutor full flatten/cancel/reconcile against broker orders and safety gate.
  - Stream auth/refresh handling and robust reconnect logic.
  - UI/controller polish, acceptance tests, Windows packaging steps.
