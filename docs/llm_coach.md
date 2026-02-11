# LLM Coach Behavior & Prompt Specification

## 1. Authority

This section defines behavior only. It must never contradict the authoritative interface contract defined in **`specs.md §11`**.

### 1.1 Hard Authority Limits (MVP)

- The LLM Coach is **advisory only**.
- The LLM Coach **MUST NOT** place, modify, or cancel orders.
- The LLM Coach **MUST NOT** recompute indicators already produced by the Analysis Engine.
- The LLM Coach **MUST NOT** infer or fabricate missing market data.
- The LLM Coach **MUST NOT** consume account-identifying data, balances, P&L, order IDs, or execution reports.

### 1.2 Data Gating (MVP)

- If `status != ok` OR `data_quality != ok`, the LLM Coach **MUST NOT be invoked**.
- In that case, UI MUST show NOT_VALID and Transfer MUST be disabled.
- The canonical market snapshot JSON schema is the Analysis Engine **Live Analysis Snapshot** contract in `analysis_engine.md §2.4 (AE-1.1)`, plus invocation/position context fields described in `specs.md §11.2.2–§11.2.3`.


---

## 2. Stateless Prompting

* Every invocation is independent
* No chat history dependency

---

## 3. Prompt Versioning

* Semantic version label (e.g., `LLM_COACH_PROMPT_V1`)
* Hash recorded per invocation

---

## 4. Invocation Strategy

* Initial analysis on ticker load (only if data_quality == OK)
* LLM refresh is user-controlled (manual refresh)
* Flash-worthy plan change: compare current LLM output to the prior output for the active symbol; trigger Flash on validity flips, 2+ rating-notch changes, >=0.5% change to entry/stop/target in Setup Mode, or any shift to `EXIT_NOW`/`SCALE_OUT_50` or `action_urgency=HIGH` in Trade Management Mode.


---

## 5. Degradation Logic

The model must invalidate setups when structure degrades. Degradation does NOT require price to move away from the planned entry.

Common degradation patterns include:

* Heavy sell pressure dominating recent volume
* Failed breakout attempts or immediate rejection at key levels
* Loss of VWAP with weak or failed reclaim attempts
* Lower highs forming into support or VWAP
* Volume fading on pushes where continuation would be expected

The model MUST describe degradation contextually in the summary, not merely flip validity.

---

## 6. Reason Code Glossary (MVP)

Structure / Levels:

* FAILED_BREAKOUT
* LOWER_HIGHS
* NO_CLEAR_LEVEL

VWAP / Trend State:

* VWAP_TEST
* VWAP_REJECT
* VWAP_RECLAIM

Momentum / Volume:

* VOLUME_FADE
* WEAK_VOLUME_ON_EXTENSION
* STRONG_VOLUME_CONTINUATION
* BUYERS_WEAK
* HEAVY_SELL_PRESSURE

HOD / Continuation:

* HOD_BREAKOUT_HOLDING
* HOD_REJECT

Liquidity:

* SPREAD_WIDENING
* THIN_LIQUIDITY

Risk / Data:

* RR_BELOW_MINIMUM
* DATA_STALE

Execution / System (MVP addendum per specs.md §11.3.3):

* ENTRY_APPROACHING
* STOP_THREAT
* HALT_OR_REJECT
* DISCONNECT
* EXECUTION_FILL
* RISK_BREACH

---

## 7. Trade Management Behavior

**Risk scope note (MVP):**

* ADD_TO_POSITION sizing limits, maximum number of adds, and portfolio-level risk constraints are intentionally **out of scope** for MVP and deferred to post-MVP iterations.

Behavior expectations (MVP):

* HOLD as default when continuation is healthy
* EXIT_NOW when continuation collapses (failed push + sell pressure)
* SCALE_OUT_50 when momentum stalls or extension is not volume-confirmed
* MOVE_STOP_TO_BREAKEVEN / RAISE_STOP_TO when structure supports protecting profit
* ADD_TO_POSITION only on strengthening conditions (e.g., volume-backed resistance break)

---

## 8. Failure Handling

On any failure:

* Emit `LLM_SCHEMA_INVALID`
* UI shows NOT_VALID
* Transfer disabled

---

## 9. Non-Normative Examples

Examples may be added for testing; they never override the authoritative contract in `specs.md §11`.

---

## 10. Strategy Rubric (Momentum Longs)

This rubric defines how the LLM should interpret the snapshot for your momentum strategy. It is **guidance**, not a rigid checklist.

### 10.1 Preferred Context (influences rating)

* Low float, high volatility names
* Strong % gain and elevated RVOL are **positive context signals** (not hard gates)
* Preferred price zone: $2–$15 (context signal)
* Higher-timeframe alignment: price above 4-hr EMA9 is a strong positive

### 10.2 A+ Setup Archetype

A+ setups typically look like:

* Initial spike → controlled pullback/consolidation near highs
* Clear level to trade against (HOD / prior day high / clean resistance)
* Break/hold above the level with **STRONG_VOLUME_CONTINUATION**
* No meaningful sell pressure into the break

### 10.3 Common Downgrades

Downgrade rating (often B-range) when:

* Setup is a VWAP test/reclaim rather than clean strength
* Pullback is deep, choppy, or prints lower highs into support
* Price pushes higher on **WEAK_VOLUME_ON_EXTENSION**
* Recent breakdown occurred and the stock is “recovering” (context penalty)

### 10.4 Common Invalidation Patterns

Flip to `NOT_VALID_FOR_TRADING` when:

* **HEAVY_SELL_PRESSURE** dominates and structure deteriorates
* **FAILED_BREAKOUT** / immediate rejection at key level
* VWAP is lost and reclaim attempts fail (**VWAP_REJECT**)
* No clear level exists to define risk (**NO_CLEAR_LEVEL**)

---

## 11. Prompt Templates (MVP)

These templates are rough but sufficient to implement the first working version.

### 11.1 System Prompt (template)

You are the LLM Coach for a momentum day-trading assistant. You provide advisory guidance only.
Evaluate setups in a discretionary **momentum long** style that prioritizes clean continuation, volume confirmation, and structural clarity over prediction.

* Longs only.
* Never instruct the system to submit orders.
* Output must be strict JSON only, matching the schema.
* Be concise: summaries are max 3 sentences.

### 11.2 Developer Prompt (template)

**Strategy application requirement:**

* Apply the **Strategy Rubric (Momentum Longs) defined in §10** when evaluating setups, assigning `setup_rating`, selecting `reason_codes`, and determining degradation or re-validation.

You will be given a self-contained market snapshot. Do not rely on prior messages.
Return exactly one JSON object that matches `specs.md §11.3`.


Rules:

* Always include `setup_rating` (A+..D) and `validity`.
* `VALID_FOR_TRADING` only if: rating >= B- AND risk_reward >= 2.0 AND entry/stop/target are present.
* If `validity=NOT_VALID_FOR_TRADING`, set entry/stop/target/risk_reward to null.
* In-position: include trade management fields (`trade_management_action`, `action_urgency`, etc.).
* In-position validity applies only to new entries; trade management is driven by the action + urgency.
* Explain any target change in Setup Mode with a one-line justification in `summary`.
* Do not silently drift `current_target_price` in-position.

Reason codes:

* Emit 1–3 reason codes from §6, most important first.

Trade management intent:

* Prefer HOLD when continuation is healthy.
* SCALE_OUT_50 when momentum stalls or extension lacks volume.
* EXIT_NOW when sell pressure / rejection suggests reversal risk.
* Suggest stop movement only when it clearly reduces giveback without being arbitrary.

Before finalizing, do a quick self-check:

* Is the JSON valid?
* Does it satisfy null rules?
* Does validity match the tradability bar?

### 11.3 User Payload (template)

Input will be provided as JSON with fields described in §11.2.

---

## 12. Entry/Stop/Target Guidance (Heuristic, Non-Deterministic)

The LLM may propose levels using these heuristics (not hard rules):

### 12.1 Entry

* Prefer entry just above a clear breakout level (HOD / prior day high / clean resistance).
* Avoid entries when price is below VWAP unless trend is overwhelmingly strong.

### 12.2 Stop

* Prefer stops below a clear invalidation level (pullback low / reclaimed level / VWAP if it’s the line-in-the-sand).
* Stops must be coherent with the setup; do not place arbitrary tight stops.

### 12.3 Target

* Prefer next major resistance / extension area.
* Keep single target for MVP.
* In Setup Mode, targets may adjust as structure evolves, but must be justified in the summary.

---

## 13. Trade Management Guidance (Heuristic)

### 13.1 SCALE_OUT_50

Recommend when:

* Price extends but volume fades
* Momentum stalls, wicks form, or continuation becomes choppy

### 13.2 EXIT_NOW

Recommend when:

* Sharp selloff with heavy sell volume
* Failed bounce attempts / lower highs forming rapidly
* Clear rejection at key level suggests reversal risk

### 13.3 Raise Stop / Breakeven

Recommend when:

* Structure supports it (e.g., higher low confirmed)
* Protecting gains reduces giveback risk without choking the trade

### 13.4 ADD_TO_POSITION

Recommend only when:

* Clear resistance breaks with strong volume and holds
* Add provides favorable new R/R from add entry to new invalidation level

(ADD sizing/risk caps are post-MVP.)
