# Recording recovery after auth/runtime interruption

## Problem

A market-day recording can end with `stop_reason=runtime_stopped` when the
Companion runtime or auth-dependent service is restarted. Schwab live data may
later recover, while the research recorder remains stopped. This creates a
dangerous state where live paper trading continues but the evidence needed for
end-of-day replay/audit is missing.

## Recovery policy

Recording intent is persisted in the Companion app-state database whenever a
recording session is active. The intent contains:

- ET trading date;
- currently active recording symbols;
- whether automatic resume is allowed;
- interruption timestamp, when applicable;
- previous recording session directory, when applicable.

A normal user/manual stop or the 15:00 ET cutoff clears the intent.

A `runtime_stopped` close preserves the intent and marks the recorder state as
recovery-pending.

On runtime startup, and then from the existing five-second watchdog loop,
Companion checks the persisted intent. Before 15:00 ET on the same date:

1. if authorization is unavailable, the recorder remains stopped and reports
   `recovery_pending=true` with `recovery_reason=awaiting_auth`;
2. once authorization is available, Companion starts a **new** recording
   session for the persisted active symbols;
3. the new session manifest records recovery lineage to the prior session and
   the interruption/recovery timestamps.

The old and new sessions are deliberately not spliced. The outage remains an
observable capture gap.

Intent from a prior ET date is discarded and will never silently start a new
day's recording. Intent is also discarded at/after the 15:00 ET cutoff.

## Research interpretation

A recovered day is a multi-session capture day. Downstream audit code should
aggregate same-date sessions where appropriate while preserving the gap between
the interrupted and recovered sessions. Any setup whose causal evidence crosses
that gap must continue to be treated as capture-compromised.

This change is infrastructure-only. It does not alter strategy thresholds,
runner definitions, entry rules, or exits.
