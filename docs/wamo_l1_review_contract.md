# Historical L1 review contract for WAMO

`POST /api/review/l1-window` reads captured `LEVELONE_EQUITIES` observations from an existing recording. **No live market connection, trade placement, paper-ledger writes, or shared replay-cursor mutation.**

Request body:

```json
{"session_id":"2026-10-09_073202_session","symbol":"OFAL","start_ms":1791540000000,"end_ms":1791540119999}
```

`start_ms` and `end_ms` are epoch milliseconds; both are inclusive. They must satisfy `0 <= start_ms <= end_ms` and span at most 120,000 milliseconds. Recordings must exist and contain the requested symbol.

Response shape:

```json
{"session_id":"...","symbol":"OFAL","window":{"start_ms":0,"end_ms":0,"future_data_included":false},"frames":[{"timestamp_ms":0,"bid":0.0,"ask":0.0,"last":0.0,"bid_size":0,"ask_size":0,"last_size":null,"volume":0}],"evidence_tier":"captured_L1_top_of_book"}
```

Example numeric values above are **shape placeholders**, not market observations. Partial captured Schwab deltas are rebuilt in timestamp order using the existing `LevelOneCache`; unknown fields remain absent/null until observed, and no unobserved quote updates are fabricated. `frames` includes observations only inside the requested inclusive interval. A successful empty window returns `frames: []`. Completed sessions are cached (LRU up to four symbol histories); active recordings are reconstructed without caching to avoid stale quotes. Errors for malformed ranges and invalid session/symbol are HTTP 400.

WAMO calls the loopback-only ToS Companion API on `127.0.0.1:4977` from its isolated, research-only multi-day replay. It must treat missing valid quotes as unresolved, not assume filled trades or zero spread. The WAMO frozen October 9 candidate filter remains unchanged; October 9 is in-sample and excluded from holdout validation. The endpoint is not a reliable order-fill simulator: only top-of-book snapshots are available, with no queue position, multi-level depth, or guaranteed executable size.
