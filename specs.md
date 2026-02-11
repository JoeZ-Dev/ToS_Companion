# Momentum Trading Companion — Specs v1.1 (Tightened, Lossless)

> **Status:** Tightened spec format intended for one-shot agentic implementation (MVP build).\
> **Build target:** MVP application build (live Schwab trading), not “App v1 release.”\
> **Lineage:** Lossless tightening of **Momentum Trading Companion — Specs v1.0 (Coding-Ready)**.\
> **Date:** 2026-02-08

## -1. Provenance, Authority, and No-Other-Docs Rule *(Clarification — Spec Factory tightening)*

### -1.1 Authoritative sources (ONLY)

This spec must be interpreted using **only** the following sources:

1. `specs.md` (baseline v1.0 requirements, preserved herein)
2. `analysis_engine.md` (AE-1.0 contract, authoritative for market profile generation)
3. Schwab API supporting documents located under `schwab/`, including:
   - `Retail_Trader_API.md`
   - `Market_Data_API.md`
   - `OAuth_Authentication_Guide.md`
   - `WebSocket_Streaming_Guide.md`
   - `Quick_Reference.md`
   - `README.md`
   - `CONVERSION_SUMMARY.md`
   - `authflow_seq_diag.jpg`


No other documents, assumptions, or “standard practices” are allowed to override or extend this spec unless explicitly added in a future, versioned revision.

### -1.2 Preservation rule (lossless)

- No baseline requirement may be deleted, weakened, or summarized away.
- Added text in v1.1 MUST be explicitly labeled as *(Clarification — Spec Factory tightening)* and must not change behavior.

### -1.3 Conflict rule

If any conflict is discovered between baseline v1.0 text and a v1.1 clarification, the baseline v1.0 text wins unless the v1.1 clarification is explicitly marked as a behavioral change (none are intended in this revision).

---

## -0. Specs v1.0 Baseline Header (Archived, Preserved Verbatim)

*(Clarification — Spec Factory tightening)* The baseline v1.0 header is preserved verbatim in **Appendix B** to avoid duplication of authoritative headers while maintaining full provenance.

---

## 0. Goal

Build a Windows-first Python desktop app that:

- Pulls live Schwab market data
- Renders a live 10-second chart with basic studies (VWAP/EMA)
- Runs a deterministic Analysis Engine (AE) snapshot
- Feeds structured market state into an optional LLM Coaching Engine
- Produces structured trade readouts (entry, stop, exit, reasoning)
- Allows controlled transfer of LLM-suggested values into live order tickets
- Supports live order execution with extended-hours constraints (EMM + synthetic stops)
- Logs a full audit trail (trade journal) for verification

Scope constraints:

- **Equities only**
- **Live trading only (Schwab does not support paper trading)**
- **Single active symbol per instance** (multiple instances encouraged)
- **Access window:** **04:00–20:00 ET**
- **Extended hours supported** (premarket + after-hours)
- **LLM coaching is optional and explicitly user-controlled**


---

## 0.1 Truth Ledger Snapshot *(Clarification — Spec Factory tightening)*

The following are **hard truths** already stated in §0 and elsewhere. They are repeated here only to prevent accidental drift during implementation:

- Asset class: **Equities only**
- Trading mode: **Live trading only** (Schwab paper trading not supported)
- Symbol model: **Single active symbol per app instance** (multiple instances encouraged)
- Allowed access window: **04:00–20:00 ET**
- Extended hours support: **SEAMLESS** includes premarket + regular + after-hours inside the access window
- The Schwab Integration Addendum is REQUIRED and considered part of the spec (baseline header)
- The Analysis Engine is **deterministic** and **non-AI** (see `analysis_engine.md`)

This section is a restatement only; baseline requirements remain authoritative.

---

## 0.2 Language & Normative Keywords *(Clarification — Spec Factory tightening)*

The following keywords are normative:

- **MUST / MUST NOT**: mandatory requirements (logic, safety, data gating, permissions, execution constraints)
- **MAY / MAY ONLY IF**: optional or conditional behavior
- **SHOULD**: non-binding guidance used only for **visual styling / aesthetics** and other non-functional presentation details

No “should” language may define trading logic, safety gates, data requirements, execution authority, or failure handling.

---

## 1. Terminology

### 1.0 Canonical Terminology Glossary *(Clarification — Spec Factory tightening)*

This glossary is intentionally capped (MVP) and is the canonical source of term meaning across `specs.md`, `analysis_engine.md`, and `llm_coach.md`.

| Canonical Term | Definition (1 line) | Allowed Aliases (if any) |
|---|---|---|
| status | `ok|error` output state from Analysis Engine used for gating | none |
| data_quality | `ok|partial|stale|no_data|error` data health indicator used for gating | none |
| market_state | `premarket|normal|afterhours` session label | session_state |
| bars_window | Capped OHLCV bars included for context (LLM receives 5m only) | bars |
| levels | Support/resistance/VWAP-related reference prices | zones |
| event | Deterministic tagged occurrence (rejection, spike, dump) | event_summary |
| signal | Deterministic detection/flag (breakout, pullback, failure) | flag |
| LLM Coach | Advisory component that suggests plans; never executes | coach |
| Suggested Trade Plan | LLM output: entry/exit/stop + rationale | plan |
| Transfer | User action that copies suggested plan values into order ticket | send_to_ticket |
| Flash notification | Non-modal alert that plan changed materially | flash |
| EMM | Chase-limit execution for extended hours | extended_market_mode |
| Synthetic order | App-managed trigger logic (not broker-native) | synthetic trigger |
| Cancel | Cancel working orders + disarm triggers (does not close position) | none |
| Flatten | Cancel then close position (session-dependent) | close_all |

- **NORMAL**: Regular session (09:30–16:00 ET)
- **SEAMLESS**: Premarket + NORMAL + after-hours (04:00–20:00 ET)
- **EMM (Extended Market Mode)**: Chase-limit execution used to simulate market-like fills in extended hours
- **Synthetic Order**: Trigger logic managed by the application (not broker)
- **Active Symbol**: The single symbol subscribed, displayed, and tradable in an app instance
- **STALE**: Most recent quote/update exceeds freshness threshold

---

## 1.1 Canonical Time & Session Semantics *(Clarification — Spec Factory tightening)*

**Canonical internal time representation**

- All timestamps used for ordering, aggregation, persistence, comparisons, and journaling MUST be normalized to **UTC epoch milliseconds**.

**ET usage**

- ET is used for **session definitions and user-facing labels** only (e.g., NORMAL 09:30–16:00 ET; SEAMLESS 04:00–20:00 ET).
- App access window is 06:00–20:00 ET. AE ‘current session’ may ingest from 04:00–20:00 ET for context; this does not change UI access/trading availability.

**Cross-document alignment**

- `analysis_engine.md` inputs use `ts_utc` as UTC ISO-8601 strings.
- The application may convert those to UTC epoch milliseconds internally, but MUST preserve UTC correctness.
- No component may “mix” ET into persisted timestamps.

---

## 2. Development & Deployment Environment (Non-Functional)

Primary dev OS: **Linux** (headless, CLI-driven)

Runtime target: **Windows 10/11**

Packaging target: **Windows EXE**

Source of truth: **GitHub repo**

Testing:

- Unit + TDD on Linux
- Smoke / runtime validation on Windows

CI expectations:

- Linux test gate required
- Windows build validation required

> This is architecture-level intent and constraints, not step-by-step instructions.
## 2.2 Windows EXE Packaging Toolchain (MVP — Decision Required)

The spec requires a Windows EXE deliverable. The packaging toolchain MUST be explicitly chosen to avoid late-stage blockers (especially with PySide6 + Qt WebEngine + Plotly assets).

**DECISION REQUIRED (choose one and lock it):**
- Option A: PyInstaller
- Option B: Nuitka
- Option C: Briefcase

**MVP default if no decision is locked:** `TODO(SPEC_CLARIFICATION)` (do NOT assume a toolchain).


---

## 2.1 No Silent Defaults *(Clarification — Spec Factory tightening)*

Global invariant:

- If a value is required for correctness/safety and **no default is explicitly defined** in this spec, the application MUST:
  1. fail loudly (surface an error),
  2. write a journal entry, and
  3. write a redacted log entry.

This prevents hidden behavior drift in agentic builds.

---

## 3. Platform & Dependencies

- Python **3.11+**
- UI: **PySide6** (Qt ≥ 6.5 recommended)
- Charting: **Plotly (pinned to 5.18–5.22)** embedded via Qt WebEngine
- Data: `httpx` / `requests` + websocket client
- Indicators: `pandas`, `numpy` (optionally `pandas-ta`)
- Storage: **SQLite (****sqlite3****, builtin)**
- Paths: **platformdirs** (required)
- Crypto: **cryptography** (Fernet)

**Portability rule:** Windows-only dependencies are prohibited unless isolated behind an interface. Hotkeys are the sole allowed exception.

---

## 4. Product Structure

### 4.1 UI Layout (MVP, Final)

**Window behavior**

- Default window size: **1400×900**
- Minimum window size: **1100×700**
- Resizable

**Main layout regions**

1. **Top bar**

- Symbol input (Enter loads)
- Connection status: `CONNECTED / RECONNECTING / STALE`
- LLM Coach toggle (default OFF)
- **Armed trigger count badge** next to LLM toggle when count > 0 (e.g., `2`)

2. **Center**

- Plotly 10s candlestick chart
- Study toggles: `VWAP`, `EMA9`, `EMA20`

3. **Right panel (Trade Ticket)**

- Quantity, Side, Session, Order Type
- Price inputs (LIMIT/STOP as applicable)
- EMM controls (when session is `SEAMLESS`)
- Bracket controls
- LLM suggested trade readout + **Apply** button
- Trigger status (including armed trigger count)
- Journal access (see §7)

4. **Options / Settings pane**

- **Hotkeys Enabled** toggle (default OFF)
- EMM settings (shown when `SEAMLESS` enabled):
  - Max slippage (%) default **1.5**
  - Chase interval (ms) default **250**
  - Max chase duration (s) default **3**
- **Persist window geometry** toggle (default ON)
- **Persist study toggles** toggle (default ON)

### 4.2 Chart View Behavior (MVP, Final)

- Zooming and panning enabled (wheel/trackpad zoom; click-drag pan)
- Y-axis ToS-style:
  - Default auto-scale ON
  - Manual y adjustments suspend auto-scale until reset
- **Reset View control:** toolbar button labeled **Reset View** (or **Auto-Scale**) restores default scaling
- Default visible window: last **180** completed 10s bars (\~30 minutes) plus current forming bar

---

## 5. Data, Aggregation, and Studies

## 5.0 Analysis Engine (AE-1.0) Integration Contract *(Clarification — Spec Factory tightening)*

This product depends on a deterministic, non-AI **Analysis Engine** defined in `analysis_engine.md`.

**Authority & immutability**

- AE-1.0 input requirements and output JSON schema are authoritative.
- The app MUST treat `market_profile.profile_json` as **read-only output** produced by the AE.
- The app MUST NOT “adapt” AE output fields silently.

**Invocation timing (explicit, non-invasive)**

- AE runs **once per symbol** (as defined by AE-1.0). This spec does not require AE to run in real time.
- If the product needs a refreshed profile, it must run AE again explicitly (no silent refresh).

**Failure behavior**

- If AE inputs are missing, malformed, or non-monotonic as prohibited by AE-1.0, the app MUST fail loudly.
- If AE output JSON is missing required fields or violates fixed cardinalities, the app MUST treat this as `DATA_INTEGRITY_ERROR` (see §14.1) and fail loudly.

---

### 5.1 Quote Timestamp Source (Final)

- Aggregation uses the most authoritative event timestamp available from streaming.
- Canonical mapping:
  - trade timestamp (preferred)
  - quote timestamp (fallback)
- Timestamp must be **ms epoch**; normalized immediately.

### 5.2 10-Second Bar Semantics (Final)

- Bars are **left-inclusive, right-exclusive**.
- If **no quotes** in a 10s window: **no bar emitted**.
- Chart must show a visible gap.
- Plotly must not connect across gaps (`connectgaps=False` or equivalent).

### 5.3 Stale Data (Final)

- Quote age > **5 seconds** → `STALE`
- Aggregation continues; current forming bar flagged stale
- Stale bar visual style: **semi-transparent gray candle body** + **clock icon** in upper-right of candle area

### 5.4 Volume Aggregation (Final)

- Volume computed as sum of per-message deltas.
- If broker provides cumulative volume: derive deltas using per-symbol baseline.
- Reset baseline on symbol change and stream reconnect (first cumulative becomes baseline → delta=0).

Volume anomaly handling:

- Negative delta → clamp to 0; log anomaly
- Unreasonably large delta → cap at `max(250_000, 10 × median_delta_last_60s)`; log anomaly

### 5.5 Studies (Final)

VWAP:

- Anchored to **04:00 ET** (extended session start) for the current ET trading day
- VWAP accumulates continuously through **20:00 ET** and **does not reset** at 09:30 ET

EMA:

- EMA lines hidden until **length × 3** completed 10s bars exist

### 5.6 Price Precision & Validation (Final)

- Display prices to **2 decimals**
- Minimum tick size assumed: **\$0.01**
- User-entered prices rounded to 2 decimals before submission
- Reject invalid prices: `<=0`, `NaN`, `None`
- Trigger comparisons use normalized 2-decimal values

---

## 6. Symbol Management

### 6.1 Single Active Symbol Model (Final)

- Exactly one active symbol per app instance
- Encourage multiple instances for multiple tickers

### 6.2 Input & Validation (Final)

- Normalize to uppercase
- Fast local validation: `^[A-Z.]{1,8}$`
- Broker validation: quote fetch / stream subscribe; invalid → error and do not switch

### 6.3 Switching Constraints (Hard Rule)

Switching is blocked if any are true:

- Any active/working broker orders exist
- Any armed synthetic triggers exist

### 6.4 Switching Behavior (Final)

- Unsubscribe stream
- Reset aggregator + in-memory buffers
- Subscribe new stream
- Fetch historical data fresh; **do not reuse local cache to seed chart**

---

## 7. Storage & Trade Journaling

### 7.1 Multi-Instance Storage Policy (Final)

- Shared credentials vault across instances
- Per-instance SQLite DB to avoid locking/overwrite:

```
user_data_dir("MomentumTradingCompanion")/instances/<instance_id>/data.db
```

- `instance_id` generated on first run (UUID) and stored in `app_state`

OAuth multi-instance rule:

- Only one instance runs interactive OAuth at a time (lock file).

### 7.2 SQLite Schema (Final)

Core tables:

- `schema_version`
- `symbols`
- `bars` (10s/1m/5m/1h/4h)
- `market_profile`
- `app_state`
- `trade_journal` (append-only)

**Authoritative baseline schema (v1.1):** The SQL below is the authoritative baseline schema for `specs.md` v1.1.  
Future schema evolution is permitted **only via explicit migrations** that increment `schema_version`. No silent schema changes are allowed.

```sql
CREATE TABLE schema_version (
    version INTEGER NOT NULL,
    applied_at_utc TEXT NOT NULL
);

CREATE TABLE symbols (
    symbol TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    last_selected_at_utc TEXT
);

CREATE TABLE bars (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL, -- '10s','1m','5m','1h','4h'
    ts_utc TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    is_extended INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'schwab',
    PRIMARY KEY (symbol, timeframe, ts_utc)
);

CREATE INDEX idx_bars_symbol_timeframe_ts
    ON bars(symbol, timeframe, ts_utc);

CREATE TABLE market_profile (
    symbol TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    PRIMARY KEY (symbol, created_at_utc)
);

CREATE TABLE app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Trade journal (append-only)
CREATE TABLE trade_journal (
    event_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    event_type TEXT NOT NULL,
    session_mode TEXT NOT NULL,
    connection_state TEXT NOT NULL,
    side TEXT,
    qty REAL,
    qty_filled REAL,
    order_type TEXT,
    limit_price REAL,
    stop_price REAL,
    broker_order_id TEXT,
    emm_active INTEGER NOT NULL DEFAULT 0,
    emm_ref_price REAL,
    emm_bound_price REAL,
    emm_attempt_n INTEGER,
    notes_json TEXT
);

CREATE INDEX idx_trade_journal_ts
    ON trade_journal(ts_utc);

CREATE INDEX idx_trade_journal_symbol_ts
    ON trade_journal(symbol, ts_utc);

-- Suggested app_state keys (not enforced by schema):
-- instance_id
-- last_symbol
-- selected_account_hash
-- ui_geometry_json
-- ui_studies_json
-- persist_window_geometry ("0"/"1")
-- persist_study_toggles ("0"/"1")
```

### 7.3 Trade Journaling (MVP, Final)

Purpose: auditable verification for EMM/synthetic logic and post-trade review.

Journal records created for:

- broker order submit/replace/cancel
- fill/partial fill
- synthetic trigger arm/disarm/fired
- flatten
- errors

Append-only: corrections are new rows.

UI:

- Journal view lists last 200 events
- Export Journal → timestamped CSV/JSON under instance data dir

### 7.4 Trade Journal Persistence & Reliability *(MVP — Intent Lock)*

- The trade journal is **append-only** and immutable in MVP.
- The event must be durably accepted by the journal subsystem (e.g., enqueued + fsync’d by writer) before UI success:
  - submit/replace/cancel
  - fills (partial/full)
  - synthetic arm/disarm/fire
  - flatten
  - Transfer action

**Failure handling**:
- If a critical journal write fails:
  - Surface a persistent banner: `Journaling failure — verification compromised`
  - Mark the session as `verification_degraded=true`
  - Continue running, but include degradation in any LLM context if enabled

---

## 8. Credential Storage & Authentication

### 8.1 Credentials Vault (Final)

- Encrypted local credential store under platformdirs.user_data_dir("MomentumTradingCompanion")
- PIN required on every app launch to unlock credential access
- On Windows: encrypt/decrypt Schwab tokens using Windows DPAPI (no plaintext tokens on disk)
- The PIN is not the encryption key; it gates access and unlocks the DPAPI-protected store
**Clarification (DPAPI vs Fernet):**
- On Windows, Schwab access/refresh tokens at rest MUST be protected with DPAPI (authoritative).
- `cryptography` (Fernet) MUST NOT be used as a substitute for DPAPI for Schwab tokens unless this spec explicitly changes that rule.
- If Fernet is used at all, it may only be for explicitly-defined non-token secrets (e.g., export bundles), and MUST be documented in this section with exact scope.

- No plaintext secrets written to disk
- Dev-only shortcuts (e.g., key-files) are forbidden unless explicitly gated behind a dev-mode flag and never used in production builds

### 8.2 First Launch & Recovery (Final)

- If missing/invalid tokens: force Connect to Schwab (interactive OAuth)
- Refresh failure: clear stored tokens → re-auth
- If PIN is reset: invalidate stored Schwab tokens and force re-auth (user must log into Schwab again)
- Persistent banner: “Session expired / locked — please re-authenticate”

### 8.3 Schwab Integration Contract (Abstract) (Final)

This spec remains **schema/wrapper-agnostic**, but the implementation MUST satisfy the following Schwab responsibilities.

**Required REST capabilities:**

* Accounts:

  * List accounts (for selection)
* Quotes:

  * Fetch a quote snapshot for symbol validation and initial UI state
* Price history:

  * Fetch historical bars for 4h/1h/5m/1m to seed chart + studies
* Orders:

  * Place order (LIMIT/MARKET/STOP per session rules)
  * Replace order (for chase / repricing)
  * Cancel order
  * Get order status (for polling)

**Broker Failure Handling Defaults (MVP):**

REST:
- **401/403** (auth invalid/expired): transition to `REAUTH_REQUIRED`, disable trading actions, and show persistent banner prompting Connect-to-Schwab.
- **429** (rate limit): apply exponential backoff with jitter (implementation-defined), show a non-modal warning banner, and continue retrying for non-order endpoints. For **order endpoints**, do not blindly retry submits; surface error and require explicit user re-attempt.
- **5xx / timeouts / network errors**: retry with backoff for non-order endpoints; for order submit/replace/cancel, surface error and reconcile via status polling before allowing repeated attempts.

Streaming:
- Subscription failure or stream disconnect MUST surface `RECONNECTING` and follow reconnect policy.
- On reconnect, re-subscribe to the active symbol and resume aggregation; do not “fill gaps” with fabricated bars.

**Required streaming capabilities:**

* Start a streaming session and subscribe to the active symbol for:

  * bid/ask/last price
  * volume (cumulative or delta)
  * authoritative timestamps (trade timestamp preferred, quote timestamp fallback)

**Streaming operational requirements:**

* Heartbeat/keepalive must be honored if required by the chosen Schwab streaming client.
* On disconnect:

  * UI must switch to `RECONNECTING`.
  * Synthetic triggers remain armed but are **inactive** until reconnect (per §9.4–§9.5).
  * EMM loops must stop and cancel remaining open quantity (per §9.3 and precedence §9.8).
* Reconnect policy:

  * Auto-reconnect with backoff (implementation-defined) until user exits.
  * After reconnect, re-subscribe to the active symbol and resume aggregation.

**OAuth callback & multi-instance rule:**

* The OAuth redirect URI must be localhost-based and pre-registered with Schwab.
* Use a fixed callback port (e.g., **8765**) for simplicity.
* If another instance is already running the interactive OAuth connect flow, additional instances must detect a lock (file lock) and instruct the user to complete auth in the first instance.

**Callback implementation requirements (MVP):**
- Redirect path MUST be explicitly defined (e.g., `http://127.0.0.1:8765/callback`). If not defined, add `TODO(SPEC_CLARIFICATION)` and do not assume.
- If port 8765 is already in use by a non-app process, the app MUST fail loudly and instruct the user how to resolve (do NOT silently choose another port unless the spec explicitly permits it).
- The app MUST explicitly define whether it auto-opens the browser for OAuth or requires manual user copy/paste. If not defined, add `TODO(SPEC_CLARIFICATION)`.

---

### 8.4 Auth & Vault State Machine *(MVP — Intent Lock)*

**States**:
- `LOCKED`: App launch state; PIN required.
- `UNLOCKED`: PIN validated; credential vault accessible.
- `TOKENS_VALID`: Schwab tokens exist and are usable.
- `TOKENS_INVALID`: Tokens missing, expired, or refresh failed.
- `REAUTH_REQUIRED`: User must complete Schwab OAuth.

**Transitions**:
- App MUST start in `LOCKED`.
- Correct PIN → `UNLOCKED`.
- Token validation determines `TOKENS_VALID` vs `TOKENS_INVALID`.
- `PIN_RESET` MUST invalidate tokens and force `REAUTH_REQUIRED`.

**Gating**:
- If not `UNLOCKED`, the app MUST NOT access tokens or place/cancel/flatten orders.
- If `REAUTH_REQUIRED`, all trading actions are disabled and a Connect-to-Schwab CTA is shown.

---

## 9. Order Execution

### 9.1 Order Types & Session Availability (Final)

| Order Type | NORMAL | SEAMLESS |
| ---------- | ------ | -------- |
| MARKET     | ✅      | ❌        |
| LIMIT      | ✅      | ✅        |
| STOP       | ✅      | ❌        |
| STOP-LIMIT | ❌      | ❌        |

Synthetic orders are used where broker-native stops are unavailable.

### 9.2 Account Selection (Final)

- On auth: list accounts
- If 1 → auto-select
- If >1 → prompt on first trade attempt
- Persist selected account hash in `app_state`

### 9.3 EMM — Chase-Limit Algorithm (Final)

Settings:

- `emm_max_slippage_pct` default **1.5**
- `emm_chase_interval_ms` default **250**
- `emm_max_chase_duration_s` default **3**

Reference price:

- Buy / buy-to-cover: current ask at trigger time
- Sell exit / buy-to-cover exit for short: current bid at trigger time

Bounds:

- Buy cap = ref × (1 + slippage%)
- Sell floor = ref × (1 − slippage%)

Loop:

1. Submit LIMIT at current ask/bid bounded by cap/floor
2. Every interval: if not fully filled, replace to latest ask/bid bounded by cap/floor
3. Stop on fill, timeout, cancel/flatten, or disconnect
4. On timeout/disconnect: cancel remaining open qty; surface status `EMM TIMEOUT` / `EMM DISCONNECTED`

Partial fills: manage remaining qty only.

### 9.4 Synthetic Stops (Extended Hours) (Final)

Trigger:

- Long exit: `bid_now <= stop_price`
- Short exit: `ask_now >= stop_price`

On trigger in SEAMLESS: execute using EMM.

Disconnect rule:

- Synthetic stops remain armed but **inactive** while disconnected.
- Persistent warning when synthetic stops armed.

### 9.5 Synthetic Entry Triggers (Final)

Auto-cancel when:

- Flatten/Cancel
- Symbol change
- App shutdown
- LLM toggle OFF

Trigger count display:

- Badge next to LLM toggle in top bar.

**Arming (explicit user action required):**

- Synthetic Entry Triggers are armed only via an explicit user action in the Order Ticket:
  - **Arm Entry Trigger** button creates a synthetic entry trigger using the **current Order Ticket** values (side, qty, entry price, session mode, execution mode).
  - The trigger fires when last price crosses the entry price in the intended direction:
    - LONG entry: last >= entry_price
- When fired, the app MUST submit the same order that would be submitted by pressing the Buy button with those ticket values (including NORMAL vs SEAMLESS behavior).

**Disarming:**

- **Disarm Entry Triggers** button disarms all armed synthetic entry triggers for the active symbol.
- Cancel/Flatten/Symbol change/App shutdown/LLM toggle OFF MUST still disarm as already specified above.

**Note:** `Transfer / Apply` does **not** arm entry triggers.

### 9.6 Cancel & Flatten Semantics (Final)

Cancel (active symbol only):

- cancel all working broker orders
- disarm all synthetic triggers
- does not close position

Flatten (active symbol only):

- perform Cancel
- close open position:
  - NORMAL: MARKET if allowed else LIMIT
  - SEAMLESS: EMM

No confirmation dialogs (MVP). (Risk mitigation is via explicit user actions like Transfer + hotkeys, not modal prompts.)

### 9.7 Order State Tracking (Final)

- Track `orders_by_id` in memory
- Poll working orders every **500ms**
- On terminal state: update UI
- On partial fill: update remaining qty; continue required management
- On reconnect: refresh and reconcile known working orders

## 9.8 Failure & State Precedence Rules *(Clarification — Spec Factory tightening)*

When multiple states/events occur near-simultaneously, the application MUST resolve them using this precedence (highest wins):

1. **Auth / credential invalidation** (missing/expired tokens, refresh failure, account access failure)
2. **Connectivity state changes** (stream disconnect/reconnect; REST critical failure)
3. **User-initiated Cancel/Flatten**
4. **EMM terminal conditions** (timeout/disconnected handling)
5. **Synthetic trigger evaluation** (arm/disarm/fired)
6. **UI rendering / cosmetics** (visual state updates)

Notes:

- Precedence affects state transitions only, not journaling. All events are still journaled.
- This does not add new behavior; it makes implicit resolution order explicit.

### 9.9 Market-State Transition Rules *(MVP — Intent Lock)*

- Session transitions (`premarket | normal | afterhours`) are first-class events.
- Synthetic triggers MUST NOT silently change behavior across session transitions.
- If behavior would differ post-transition, the system MUST surface a Flash notification and require explicit re-arming.
- Partial fills MUST track remaining quantity and protection independently.
- The system MUST NOT auto-cancel or auto-replace orders during session transitions.

---

## 10. Hotkeys

- App-focused only
- Controlled by Hotkeys Enabled toggle (default OFF)

Default bindings:

- Buy: `CTRL+B`
- Sell: `CTRL+S`
- Flatten: `CTRL+F`
- Cancel: `CTRL+SHIFT+C`

Remapping: MVP+1 (out of scope for MVP).

---

## 11. LLM Coach (MVP-Compatible)

### 11.0 Document Authority (LLM Coach)

This document (`specs.md`) is the single source of truth for the **LLM Coach interface contract**.

Specifically, `specs.md` is authoritative for:

* Inputs passed to the LLM Coach
* Output formats and schemas
* User-visible UI fields and panel behavior
* Button semantics and safety guarantees
* Journaling and audit events

All LLM Coach behavioral logic, prompt templates, reasoning rules, degradation criteria, and internal mapping details
are defined in the **LLM Coach behavior and prompt specification document (`llm_coach.md`)** and MUST conform to the contracts defined here.

If any conflict exists, **this document (`specs.md §11`) takes precedence**.

### 11.0.1 LLM Provider & Interface Contract *(MVP — Intent Lock)*

- LLM access MUST be via an adapter interface.
- Exactly one provider/model is active at a time and declared via configuration.
- Requests MUST be bounded (hard timeout, low/zero temperature, max tokens).
- Responses MUST validate against the authoritative schema.
- Invalid responses MUST surface NOT_VALID and be journaled as `llm_invalid_schema`.
- No automatic retries unless explicitly user-initiated.
- Only contracted inputs may be sent; no account identifiers, balances, P&L, or execution reports.
- Invocation is user-controlled; no autonomous transfer or execution.


---

### 11.1 Scope, Capabilities, and Constraints

The LLM Coach is an advisory analysis component designed to evaluate live market snapshots and provide trade guidance.

**Always true:**

* Does NOT submit orders
* Does NOT arm triggers
* Does NOT autonomously execute trades

**MVP constraints:**

* **Longs only**
* Single-target analysis
* Operates both pre-entry and in-position

---

### 11.2 LLM Coach Inputs (Contracted)

Each invocation receives a complete, self-contained market snapshot.
No conversational memory is permitted.

**Canonical payload schema:** The canonical JSON object passed as the market snapshot is the Analysis Engine **Live Analysis Snapshot** contract defined in `analysis_engine.md §2.4 (AE-1.1)`. This §11.2 section is **semantic requirements and UI context**; it does not redefine the JSON schema.


#### 11.2.1 Market Snapshot

**Input availability rules:**

* Listed fields may be missing depending on data availability.
* Missing optional fields (e.g., VWAP bands, EMAs, detailed volume metrics) MUST NOT invalidate an evaluation by themselves.
* When key context fields are missing, the LLM MUST downgrade `setup_rating` or include appropriate `reason_codes`, rather than force `NOT_VALID_FOR_TRADING`.
* This guidance applies only when AE gating is satisfied (`status=ok` AND `data_quality=ok`). If AE gating fails, the LLM MUST NOT be invoked.
* Symbol
* Session mode (`NORMAL` | `SEAMLESS`)
* Timeframes
* Bid / Ask
* VWAP + bands (if available)
* EMAs
* Volume metrics
* Market state (fresh, halted, etc.)

#### 11.2.2 Invocation Context

* `invocation_type`: `TICKER_LOAD` | `MANUAL_RECALC`
* `as_of_ts`

#### 11.2.3 Position Context (only when in trade)

* `in_position`
* `side`: `LONG`
* `entry_price`
* `qty`
* `current_stop_loss` (nullable)
* `current_target_price` (nullable)

#### 11.2.4 Cadence Rules

* Run on ticker load
* Skip refresh if prior call still running
* **Manual Re-calc:** always allowed, but MAY be globally rate-limited to protect system stability.

---

### 11.3 LLM Coach Output Schema (Authoritative)

#### 11.3.1 Setup Evaluation

Fields:

* `validity`: `VALID_FOR_TRADING` | `NOT_VALID_FOR_TRADING`
* `setup_rating`: `A+ A A- B+ B B- C+ C C- D`
* `entry_price`: number | null
* `stop_loss`: number | null
* `target_price`: number | null
* `risk_reward`: number | null
* `summary`: ≤ 3 sentences
* `reason_codes`: string[]

**Tradability bar (MVP):**

* Rating ≥ `B-`
* `risk_reward ≥ 2.0`
* Entry + stop + target present

Otherwise → `NOT_VALID_FOR_TRADING`

`setup_rating` MUST still be populated even when `validity=NOT_VALID_FOR_TRADING`; in this case the rating is **informational only**.

The model is expected to downgrade validity if conditions degrade. The model MAY later re-validate a setup if structure materially improves; no hysteresis is enforced.

**Target stability rules:**

* **Pre-entry (Setup Mode):** `target_price` MAY change between evaluations, but any change MUST be explicitly explained in the `summary` with a one-line justification (e.g., expansion of HOD, new resistance identified).
* **In-position (Trade Management Mode):** `current_target_price` MUST NOT silently drift. Any change to exit expectations MUST be expressed via an explicit trade management action and explained in `management_summary`.

---

#### 11.3.2 Trade Management (In Position)

Additional fields when `in_position=true`:

**Validity clarification:**

* When `in_position=true`, `validity` applies only to **new entries**.

* In-position decisions are driven by `trade_management_action` and `action_urgency`.

* `validity` MUST NOT be used to imply whether the existing position should be held or exited.

* `trade_management_action`:

  * HOLD
  * EXIT_NOW
  * SCALE_OUT_50
  * MOVE_STOP_TO_BREAKEVEN
  * RAISE_STOP_TO
  * ADD_TO_POSITION

* `action_urgency`: LOW | MEDIUM | HIGH

* `updated_stop_loss`: number | null

* `add_entry_price`: number | null

* `add_qty`: number | null

* `management_summary`: ≤ 3 sentences

All actions are advisory only.

---

### 11.4 LLM Coach Panel (UI Contract)

**Setup Mode:**

* Validity banner
* Setup rating
* Entry / Stop / Target
* Risk/Reward (tooltip: `(target-entry)/(entry-stop)`)
* Summary

**Trade Management Mode:**

* Setup Mode elements (validity banner and rating) MAY remain visible for context but MUST NOT drive in-trade decisions.
* Trade management actions and urgency take precedence in this mode.
* Prominent action callout
* Stop / add guidance when applicable
* Management summary

**Alerting:**

* `EXIT_NOW`, `SCALE_OUT_50`, or `action_urgency=HIGH` → high-visibility (red / flash)
**Flash-worthy plan change (Setup Mode):** On each new LLM result, compare to the immediately prior result for the active symbol. Raise a Flash notification if ANY of the following occur:
- `validity` flips between `VALID_FOR_TRADING` and `NOT_VALID_FOR_TRADING`
- `setup_rating` changes by **2 or more** letter-notches (e.g., A → B-, B → C+)
- `entry_price`, `stop_loss`, or `target_price` changes by **>= 0.5%** (absolute percent vs prior value)
- Any new `reason_code` appears with “severity HIGH” semantics (implementation-defined mapping) OR `risk_reward` drops below 2.0 when previously >= 2.0

**Flash-worthy plan change (In Position):** Always Flash when:
- `trade_management_action` changes to `EXIT_NOW` or `SCALE_OUT_50`
- `action_urgency` becomes `HIGH`
* High-visibility alerts SHOULD auto-clear on the next LLM update unless reasserted by a new HIGH-urgency action.

---

### 11.5 Controls

* **Explain** → reveals `reason_codes`
* **Transfer / Apply (Setup)** → Limit + OCO (no submit, no arm)
* **Transfer / Apply (In Trade)** → modify / scale / add / flatten (no submit)
* **Re-calculate** → same prompt version, fresh snapshot

---

### 11.6 Journaling

Events:

* LLM_REQUEST_SENT
* LLM_RESPONSE_RECEIVED
* LLM_SCHEMA_INVALID
* LLM_TRANSFER_APPLIED

---

## 12. Concurrency & Threading Rules (Final)

Hard rules:

- UI thread must never block on network or DB.
- Streaming client runs in a worker thread.
- REST calls run in a worker thread / async loop.
- All DB writes are serialized through a single writer queue/worker.
- Journal writes must be non-blocking (enqueue events).
- Order polling loop runs in a worker context and posts UI updates via signals.

---

## 13. Module Boundaries (Architecture Guardrails)

The implementation MUST map responsibilities to these modules (names may vary; ownership may not):

- `SchwabRestClient`: REST calls (accounts/quotes/history/orders)
- `SchwabStreamClient`: connect/subscribe/reconnect; emits canonical quote events
- `BarAggregator10s`: builds 10s bars from quote events
- `IndicatorsEngine`: VWAP/EMA computation
- `TradeExecutor`: routes orders by session rules (NORMAL vs SEAMLESS)
- `EMMEngine`: chase-limit loop with bounds/timeouts
- `SyntheticTriggerEngine`: arm/disarm/trigger synthetic entries/stops
- `JournalWriter`: append-only journal writes + export
- `AppStateStore`: read/write app\_state keys + persistence toggles
- `UIController`: coordinates UI state, signals/slots, and renders updates

## 13.1 Canonical Quote Event Schema (MVP — Required)

`SchwabStreamClient` MUST emit a normalized, validated event shape consumed by:
- `BarAggregator10s`
- `SyntheticTriggerEngine`
- any UI quote display state

**Schema (required fields):**
- `ts_utc`: string (UTC ISO-8601, source timestamp preferred; fallback allowed but must be labeled)
- `symbol`: string
- `bid`: float | null
- `ask`: float | null
- `last`: float | null
- `bid_size`: float | int | null
- `ask_size`: float | int | null
- `last_size`: float | int | null
- `volume`: float | int | null
- `source_ts_type`: enum(`TRADE_TS`, `QUOTE_TS`, `LOCAL_INGEST_TS`)
- `raw_source`: enum(`SCHWAB_STREAM`)

**Rules:**
- If the inbound stream message cannot be mapped/validated, treat as `DATA_INTEGRITY_ERROR`, fail loudly, and journal the event.
- “No bar if no quote”: `BarAggregator10s` MUST NOT emit a bar for a 10s window if no canonical events arrived in that window.

---

## 14. Logging, Errors, and Diagnostics

## 14.1 Error Taxonomy *(Clarification — Spec Factory tightening)*

For journaling and logging consistency, surfaced errors SHOULD be classified into one of these categories (labels are descriptive; handling remains as already specified):

- `AUTH_ERROR` — OAuth/token issues, account access failures
- `CONNECTIVITY_ERROR` — stream disconnects, REST timeouts, reconnect loops
- `EXECUTION_ERROR` — order submit/replace/cancel failures, EMM loop failures
- `DATA_INTEGRITY_ERROR` — schema mismatch, impossible/invalid state, invalid AE JSON, corrupted DB / schema version mismatch
- `USER_INPUT_ERROR` — invalid symbol format, invalid prices, invalid quantities

If an error does not fit a category, use `DATA_INTEGRITY_ERROR` as the safest default (fail loudly).

---

Logging:

- Use `logging` or `structlog`
- Log file: `platformdirs.user_log_dir("MomentumTradingCompanion")/app.log`
- Never log tokens/account hashes/raw quote streams

Error handling:

- Non-blocking modal: “Something went wrong — see logs”
- Button: Copy error details
- Errors must never crash UI thread

Copy payload must include:

- app version
- instance\_id
- active symbol
- connection state
- session mode
- exception type/message/stack
- log path
- last 200 log lines (redacted)


## 14.2 LLM Recommendation Logging

LLM coaching is advisory-only and MUST NOT directly execute trades.

To preserve auditability while avoiding excessive log noise, the system MUST log LLM recommendation events only when recommendation state changes or when explicitly triggered by the user.

### 14.2.1 When to Log

Log an `LLM_RECOMMENDATION_EVENT` when:

* A new recommendation is generated and differs materially from the previous recommendation for the active symbol.
* The user manually triggers a fresh LLM analysis.
* The LLM transitions between states (e.g., NO_SETUP → VALID_SETUP, VALID_SETUP → INVALIDATED).
* The user transfers LLM values into the order ticket.
* The LLM is toggled ON or OFF.

Do NOT log every incremental LLM response or streaming update.

---

### 14.2.2 Definition of “Recommendation Change”

A recommendation is considered changed if any of the following fields differ from the last logged state:

* `direction` (LONG / SHORT / NONE)
* `entry_price`
* `stop_price`
* `target_price`
* `setup_validity_state`
* `confidence_label` (if defined in LLM contract)

Minor textual reasoning changes alone do NOT constitute a material change.

---

### 14.2.3 Required Log Fields

Each `LLM_RECOMMENDATION_EVENT` MUST include:

* `ts_utc`
* `instance_id`
* `symbol`
* `session_mode`
* `ae_snapshot_id` (or hash of AE snapshot JSON)
* `llm_model_identifier`
* `llm_prompt_version_hash`
* `recommendation_struct` (validated structured output only)
* `previous_recommendation_hash`
* `trigger_type` (AUTO_CHANGE / MANUAL_TRIGGER / TRANSFER / TOGGLE)
* `transfer_to_ticket` (boolean)
* `modified_before_execution` (boolean, if applicable)

Raw, full-text LLM responses SHOULD NOT be logged unless explicitly required for debugging.

---

### 14.2.4 Audit Integrity

* The LLM output MUST be schema-validated before logging.
* If validation fails, classify as `DATA_INTEGRITY_ERROR`.
* Journal entries MUST allow reconstruction of:

  * What the LLM recommended
  * What the user executed
  * Whether the recommendation was modified before execution

This enables post-trade verification and LLM performance evaluation.

---

## 15. Lifecycle

Startup:

- If missing/invalid credentials → force auth
- LLM default OFF
- Restart recovery: if last\_symbol present, load last 180 completed 10s bars before live aggregation
- If persistence toggles enabled, restore window geometry and study toggle state

Shutdown:

1. Disconnect streaming
2. Cancel all armed synthetic triggers
3. Flush DB writes
4. Wait up to 3 seconds then exit

---

## 16. Non-Goals (MVP)

Explicitly out of scope for MVP:

- Options/futures/crypto
- Level 2 / order book
- Multi-symbol within one instance
- Full ToS chart feature parity
- Auto-update system
- Hotkey remapping UI
- Advanced indicators beyond VWAP/EMA

---

## 17. Acceptance Tests & Definition of Done (MVP)

### 17.1 Definition of Done

MVP is considered DONE when:

- A Windows EXE build exists and runs on Windows 10/11
- Schwab Addendum smoke tests all PASS (auth, accounts, quotes, history, streaming, orders)
- Core MVP acceptance tests (below) pass
- Trade journal exports successfully (CSV/JSON) and contains required event types
- No secrets are logged; credentials are encrypted at rest

### 17.2 Acceptance Tests (Must Pass)

Aggregation & chart:

- 10s bars follow left-inclusive/right-exclusive semantics
- Missing 10s windows emit no bar and show a visible gap
- Plotly does not connect across gaps
- STALE triggers at >5s and stale style applies to forming bar
- Reset View restores default scaling

Studies:

- VWAP resets at **04:00 ET** and includes premarket prints (does not reset at 09:30 ET)
- EMA hidden until length×3 completed bars exist

Execution:

- NORMAL supports MARKET/LIMIT/STOP per table
- SEAMLESS uses LIMIT only; EMM executes market-like behavior
- EMM respects slippage cap, chase interval, and max duration
- On EMM timeout: remaining qty canceled and `EMM TIMEOUT` surfaced
- On disconnect during EMM: remaining qty canceled and `EMM DISCONNECTED` surfaced

Synthetic stops:

- Trigger fires when bid/ask crosses stop condition
- While disconnected: synthetic stops remain armed but inactive; warning visible

Orders & state:

- Order status polling occurs every 500ms while working
- Partial fills update remaining qty and continue management
- On reconnect: reconcile working orders

Journal:

- Required event types are written for submit/replace/cancel/fill/trigger/flatten/error
- Journal view shows last 200 events
- Export produces a file in instance data directory

Non-functional:

- UI thread remains responsive during streaming, DB writes, and order polling
- Linux CI unit tests pass; Windows build validation passes

## 17.3 Acceptance Test Authority Map *(Clarification — Spec Factory tightening)*

The Acceptance Tests in §17.2 are mandatory. Their authority sources are:

- **Spec-derived**: All tests listed in §17.2 are required by this spec.
- **AE-derived** (`analysis_engine.md`): Any tests involving market profile creation, schema validity, fixed cardinalities, and deterministic outputs are additionally governed by AE-1.0.
- **Schwab Addendum–derived**: The line item “Schwab Addendum smoke tests all PASS” is governed by the Schwab Addendum referenced in the baseline header.

This section does not alter the test list; it preserves authority to prevent tests being incorrectly treated as optional.

---

**End of Specs v1.0**

