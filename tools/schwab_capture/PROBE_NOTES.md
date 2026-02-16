# Schwab API Probe Notes (2026-02-09)

These notes summarize redaction-safe probes run with refreshed tokens. Only paths, params, status, and top-level keys are recorded.

## Market Data

- Quotes: `GET /marketdata/v1/quotes` with query `symbols` → 200; top-level key includes symbol (e.g., `AAPL`).
- Price History (working shape): `GET /marketdata/v1/pricehistory` with query params `symbol`, `periodType`, `period`, `frequencyType`, `frequency` → 200. Top-level keys: `candles`, `empty`, `symbol`. Candle keys: `datetime`, `open`, `high`, `low`, `close`, `volume`.
- Price History (non-working shapes):
  - Path variant `/marketdata/v1/{symbol}/pricehistory` → 404.
  - Date-bounded variant using `startDate`, `endDate`, `frequencyType`, `frequency`, `symbol` → 400 (top-level `errors`).
- Price History (epoch + flags):
  - `GET /marketdata/v1/pricehistory` with `symbol`, `startDate`, `endDate` as epoch ms strings, `frequencyType`, `frequency`, `needExtendedHoursData=true`, `needPreviousClose=true` → 200; top-level keys include `candles`, `empty`, `symbol`, `previousClose`, `previousCloseDate`. Candle keys unchanged.
  - Same with `needExtendedHoursData=false`, `needPreviousClose=false` → 200; top-level keys `candles`, `empty`, `symbol`.

## Trader

- `GET /trader/v1/accounts/accountNumbers` → 200; item keys: `accountNumber`, `hashValue`.
- `GET /trader/v1/accounts` → 200; item keys include `aggregatedBalance`, `securitiesAccount`.
- `GET /trader/v1/userPreference` → 200; top-level keys: `accounts`, `offers`, `streamerInfo`.
- `GET /trader/v1/orders` with `fromEnteredTime`/`toEnteredTime` + `maxResults`: 200; no orders returned (empty list).
- `GET /trader/v1/accounts/{hash}/orders` with same params: 200; no orders returned (empty list).

## Stream (prior capture)

- `LEVELONE_EQUITIES` works with numeric fields `1`=bid, `2`=ask, `3`=last, `4`=bid_size, `5`=ask_size, `8`=cumulative volume; top-level `timestamp` is authoritative. `QUOTE` service returned code 11 (unavailable) in capture.

## Market Hours

- `GET /marketdata/v1/markets` (no params) → 400 with `errors`.
- `GET /marketdata/v1/markets/equity` → 200; top-level key: `equity`.

## Quotes (multi)

- `GET /marketdata/v1/quotes` with `symbols=AAPL,MSFT` → 200; top-level keys: `AAPL`, `MSFT`.
