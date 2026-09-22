# Intraday market-data recorder

Records replay-grade raw Schwab market events for manually selected momentum candidates.

## Default capture

The normal recorder uses Schwab `LEVELONE_EQUITIES` only and preserves the raw deltas per symbol, including bid, ask, last, sizes, total volume, and whatever subscribed metadata Schwab actually returns. It does **not** reduce the stream to 10-second candles.

Each run creates a session directory under `~/.tos_companion/recordings` by default, containing one `<SYMBOL>.jsonl` file plus `manifest.json`. Multiple symbols share one stream connection. The process automatically stops at **3:00 PM America/New_York**.

## Run

```bash
python tools/record_market_day.py AEHL TOPS DDC
```

Optional output location:

```bash
python tools/record_market_day.py AEHL TOPS --output-root /data/momentum-recordings
```

## Schwab authorization

The recorder intentionally reuses ToS_Companion's existing `TokenProvider` / `companion_auth` path. It must not create or own a second Schwab app, refresh token, or separate OAuth flow.

## Experimental T&S probe

`TIMESALE_EQUITY` is not exposed by the supported `schwab-py` convenience API and has not been proven against Schwab's gateway. It is therefore **off by default**. A controlled live probe can be attempted explicitly:

```bash
python tools/record_market_day.py AEHL --probe-timesales
```

This is an experiment, not a production dependency. If Schwab rejects the raw service, normal L1 recording remains the baseline. The replay/execution simulator should treat T&S as an optional higher-fidelity evidence source rather than assuming it is always available.
