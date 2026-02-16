# Market Data

**Version:** 1.0.0  
**OpenAPI Version:** 3.0.3

Trader API - Market data

## Base URL

```
https://api.schwabapi.com/marketdata/v1
```

## Authentication

### oauth

**Type:** oauth2  
**Flow:** authorizationCode  
**Authorization URL:** `https://api.schwabapi.com/v1/oauth/authorize?response_type=code&client_id=fnB6k1X6JSFlQHravRt6T9m86AZlkD04&scope=readonly&redirect_uri=https://developer.schwab.com/oauth2-redirect.html`  
**Token URL:** `https://api.schwabapi.com/v1/oauth/token`  

**Scopes:**

## Table of Contents

- [Endpoints](#endpoints)
  - [/chains](#chains)
  - [/expirationchain](#expirationchain)
  - [/instruments](#instruments)
  - [/instruments/{cusip_id}](#instrumentscusip_id)
  - [/markets](#markets)
  - [/markets/{market_id}](#marketsmarket_id)
  - [/movers/{symbol_id}](#moverssymbol_id)
  - [/pricehistory](#pricehistory)
  - [/quotes](#quotes)
  - [/{symbol_id}/quotes](#symbol_idquotes)
- [Schemas](#schemas)

## Endpoints

### /chains

<a name="chains"></a>

#### GET

**Summary:** Get option chain for an optionable Symbol  
**Description:** Get Option Chain including information on options contracts associated with each expiration.  
**Operation ID:** `getChain`  
**Tags:** Option Chains  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `symbol` | query | ✓ | string | Enter one symbol |
| `contractType` | query |  | string (`CALL`,`PUT`,`ALL`) | Contract type |
| `strikeCount` | query |  | integer | Number of strikes above/below at-the-money |
| `includeUnderlyingQuote` | query |  | boolean | Include underlying quote |
| `strategy` | query |  | string (`SINGLE`,`ANALYTICAL`,`COVERED`,`VERTICAL`,`CALENDAR`,`STRANGLE`,`STRADDLE`,`BUTTERFLY`,`CONDOR`,`DIAGONAL`,`COLLAR`,`ROLL`) | Option strategy (ANALYTICAL enables theoretical inputs) |
| `interval` | query |  | number (double) | Strike interval for spread strategies |
| `strike` | query |  | number (double) | Strike price |
| `range` | query |  | string | Range (ITM/NTM/OTM etc.) |
| `fromDate` | query |  | string (date) | From date (yyyy-MM-dd) |
| `toDate` | query |  | string (date) | To date (yyyy-MM-dd) |
| `volatility` | query |  | number (double) | Volatility (ANALYTICAL only) |
| `underlyingPrice` | query |  | number (double) | Underlying price (ANALYTICAL only) |
| `interestRate` | query |  | number (double) | Interest rate (ANALYTICAL only) |
| `daysToExpiration` | query |  | integer | Days to expiration (ANALYTICAL only) |
| `expMonth` | query |  | string (JAN..DEC, ALL) | Expiration month |
| `optionType` | query |  | string | Option type |
| `entitlement` | query |  | string (`PN`,`NP`,`PP`) | Retail entitlement flag |

**Responses:**

**200** - The Chain for the symbol was returned successfully.  
  - Content-Type: `application/json`
  - Schema: [OptionChain](#optionchain)

**400** - No description  

**401** - No description  

**404** - No description  

**500** - No description  

---

### /expirationchain

<a name="expirationchain"></a>

#### GET

**Summary:** Get option expiration chain for an optionable symbol  
**Description:** Get Option Expiration (Series) information for an optionable symbol.  Does not include individual options contracts for the underlying.  
**Operation ID:** `getExpirationChain`  
**Tags:** Option Expiration Chain  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `symbol` | query | ✓ | string | Enter one symbol |

**Responses:**

**200** - The Expiration Chain for the symbol was returned successfully.  
  - Content-Type: `application/json`
  - Schema: [ExpirationChain](#expirationchain)

**400** - No description  

**401** - No description  

**404** - No description  

**500** - No description  

---

### /instruments

<a name="instruments"></a>

#### GET

**Summary:** Get Instruments by symbols and projections.  
**Description:** Get Instruments details by using different projections.  Get more specific fundamental instrument data by using fundamental as the projection.  
**Operation ID:** `getInstruments`  
**Tags:** Instruments  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `markets` | query | ✓ | array | List of markets |
| `date` | query |  | string (date) | YYYY-MM-DD; defaults to current day (up to +1 year) |

**Responses:**

**200** - OK  
  - Content-Type: `application/json`

**400** - No description  

**401** - No description  

**500** - No description  

---

### /instruments/{cusip_id}

<a name="instrumentscusip_id"></a>

#### GET

**Summary:** Get Instrument by specific cusip  
**Description:** Get basic instrument details by cusip  
**Operation ID:** `getInstrumentsByCusip`  
**Tags:** Instruments  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `` |  |  |  |  |

**Responses:**

**200** - OK  
  - Content-Type: `application/json`
  - Schema: [InstrumentResponse](#instrumentresponse)

**400** - No description  

**401** - No description  

**404** - No description  

**500** - No description  

---

### /markets

<a name="markets"></a>

#### GET

**Summary:** Get Market Hours for different markets.  
**Description:** Get Market Hours for dates in the future across different markets.  
**Operation ID:** `getMarketHours`  
**Tags:** MarketHours  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `market_id` | path | ✓ | string (`equity`,`option`,`bond`,`future`,`forex`) | Market id |
| `date` | query |  | string (date) | YYYY-MM-DD; defaults to current day (up to +1 year) |

**Responses:**

**200** - OK  
  - Content-Type: `application/json`

**400** - No description  

**401** - No description  

**500** - No description  

---

### /markets/{market_id}

<a name="marketsmarket_id"></a>

#### GET

**Summary:** Get Market Hours for a single market.  
**Description:** Get Market Hours for dates in the future for a single market.  
**Operation ID:** `getMarketHour`  
**Tags:** MarketHours  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `symbol` | query | ✓ | string | Symbol of a security |
| `projection` | query | ✓ | string (`symbol-search`,`symbol-regex`,`desc-search`,`desc-regex`,`search`,`fundamental`) | Search mode |

**Responses:**

**200** - OK  
  - Content-Type: `application/json`

**400** - No description  

**401** - No description  

**404** - No description  

**500** - No description  

---

### /movers/{symbol_id}

<a name="moverssymbol_id"></a>

#### GET

**Summary:** Get Movers for a specific index.  
**Description:** Get a list of top 10 securities movement for a specific index.  
**Operation ID:** `getMovers`  
**Tags:** Movers  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `symbol_id` | path | ✓ | string (`$DJI`,`$COMPX`,`$SPX`,`NYSE`,`NASDAQ`,`OTCBB`,`INDEX_ALL`,`EQUITY_ALL`,`OPTION_ALL`,`OPTION_PUT`,`OPTION_CALL`) | Index symbol |
| `sort` | query |  | string (`VOLUME`,`TRADES`,`PERCENT_CHANGE_UP`,`PERCENT_CHANGE_DOWN`) | Sort attribute |
| `frequency` | query |  | integer (`0,1,5,10,30,60`) | Movers frequency bucket |

**Responses:**

**200** - Analytics for the symbol was returned successfully.  
  - Content-Type: `application/json`

**400** - No description  

**401** - No description  

**404** - No description  

**500** - No description  

---

### /pricehistory

<a name="pricehistory"></a>

#### GET

**Summary:** Get PriceHistory for a single symbol and date ranges.  
**Description:** Get historical Open, High, Low, Close, and Volume for a given frequency (i.e. aggregation).  Frequency available is dependent on periodType selected.  The datetime format is in EPOCH milliseconds.  
**Operation ID:** `getPriceHistory`  
**Tags:** PriceHistory  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `symbol` | query | ✓ | string | Equity symbol (e.g., AAPL) |
| `periodType` | query |  | string | Chart period: `day`, `month`, `year`, `ytd` |
| `period` | query |  | integer | Number of periods; valid values depend on `periodType` |
| `frequencyType` | query |  | string | Time frequency; valid values depend on `periodType` |
| `frequency` | query |  | integer | Frequency interval; valid values depend on `frequencyType` |
| `startDate` | query |  | integer (ms epoch) | Start time; optional when using date-bounded form |
| `endDate` | query |  | integer (ms epoch) | End time; optional when using date-bounded form |
| `needExtendedHoursData` | query |  | boolean | Include extended-hours data |
| `needPreviousClose` | query |  | boolean | Include previous close fields |

**Responses:**

**200** - Get all candles for given date range  
  - Content-Type: `application/json`
  - Schema: [CandleList](#candlelist)

**400** - No description  

**401** - No description  

**404** - No description  

**500** - No description  

---

### /quotes

<a name="quotes"></a>

#### GET

**Summary:** Get Quotes by list of symbols.  
**Operation ID:** `getQuotes`  
**Tags:** Quotes  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `symbols` | query | ✓ | string | Comma-separated list of symbols (e.g., `AAPL,BAC,$SPX`) |
| `fields` | query |  | string | Comma-separated root nodes: `quote,fundamental,extended,reference,regular`; omit for full response |
| `indicative` | query |  | boolean | Include indicative ETF symbols (e.g., `$ABC.IV` when true) |

**Responses:**

**200** - Quote Response  
  - Content-Type: `application/json`
  - Schema: [QuoteResponse](#quoteresponse)

**400** - No description  

**401** - No description  

**500** - No description  

---

### /{symbol_id}/quotes

<a name="symbol_idquotes"></a>

#### GET

**Summary:** Get Quote by single symbol.  
**Operation ID:** `getQuote`  
**Tags:** Quotes  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `symbol_id` | path | ✓ | string | Symbol of instrument (e.g., `TSLA`) |
| `fields` | query |  | string | Comma-separated root nodes: `quote,fundamental,extended,reference,regular`; omit for full response |

**Responses:**

**200** - Quote Response  
  - Content-Type: `application/json`
  - Schema: [QuoteResponse](#quoteresponse)

**400** - No description  

**401** - No description  

**404** - No description  

**500** - No description  

---

## Schemas

<a name="schemas"></a>

### AssetMainType

Instrument's asset type


**Type:** Enum (string)


**Allowed Values:**
- `BOND`
- `EQUITY`
- `FOREX`
- `FUTURE`
- `FUTURE_OPTION`
- `INDEX`
- `MUTUAL_FUND`
- `OPTION`

---

### Bond

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `cusip` | string |  |  |
| `symbol` | string |  |  |
| `description` | string |  |  |
| `exchange` | string |  |  |
| `assetType` | string<br>Values: `BOND`, `EQUITY`, `ETF`, `EXTENDED`, `FOREX`, `FUTURE`, `FUTURE_OPTION`, `FUNDAMENTAL`, `INDEX`, `INDICATOR`... |  |  |
| `bondFactor` | string |  |  |
| `bondMultiplier` | string |  |  |
| `bondPrice` | number |  |  |
| `type` | string<br>Values: `BOND`, `EQUITY`, `ETF`, `EXTENDED`, `FOREX`, `FUTURE`, `FUTURE_OPTION`, `FUNDAMENTAL`, `INDEX`, `INDICATOR`... |  |  |

---

### Candle

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `close` | number (double) |  |  |
| `datetime` | integer (int64) |  |  |
| `datetimeISO8601` | string (yyyy-MM-dd) |  |  |
| `high` | number (double) |  |  |
| `low` | number (double) |  |  |
| `open` | number (double) |  |  |
| `volume` | integer (int64) |  |  |

---

### CandleList

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `candles` | array |  |  |
| `empty` | boolean |  |  |
| `previousClose` | number (double) |  |  |
| `previousCloseDate` | integer (int64) |  |  |
| `previousCloseDateISO8601` | string (yyyy-MM-dd) |  |  |
| `symbol` | string |  |  |

---

### ContractType

Indicates call or put


**Type:** Enum (string)


**Allowed Values:**
- `P`
- `C`

---

### DivFreq

Dividend frequency 1 – once a year or annually 2 – 2x a year or semi-annualy 3 - 3x a year (ex. ARCO, EBRPF) 4 – 4x a year or quarterly 6 - 6x per yr or every other month 11 – 11x a year (ex. FBND, FCOR) 12 – 12x a year or monthly


---

### EquityAssetSubType

Asset Sub Type (only there if applicable)


**Type:** Enum (string)


**Allowed Values:**
- `COE`
- `PRF`
- `ADR`
- `GDR`
- `CEF`
- `ETF`
- `ETN`
- `UIT`
- `WAR`
- `RGT`
- `None`

---

### EquityResponse

Quote info of Equity security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `assetMainType` | AssetMainType |  |  |
| `assetSubType` | EquityAssetSubType |  |  |
| `ssid` | integer (int64) |  | SSID of instrument |
| `symbol` | string |  | Symbol of instrument |
| `realtime` | boolean |  | is quote realtime |
| `quoteType` | QuoteType |  |  |
| `extended` | ExtendedMarket |  |  |
| `fundamental` | Fundamental |  |  |
| `quote` | QuoteEquity |  |  |
| `reference` | ReferenceEquity |  |  |
| `regular` | RegularMarket |  |  |

---

### Error

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) |  | Unique error id. |
| `status` | string<br>Values: `400`, `401`, `404`, `500` |  | The HTTP status code . |
| `title` | string |  | Short error description. |
| `detail` | string |  | Detailed error description. |
| `source` | ErrorSource |  |  |

---

### ErrorResponse

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `errors` | array |  |  |

---

### ErrorSource

Who is responsible for triggering these errors.


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `pointer` | array |  | list of attributes which lead to this error message. |
| `parameter` | string |  | parameter name which lead to this error message. |
| `header` | string |  | header name which lead to this error message. |

---

### ExerciseType

option contract exercise type America or European


**Type:** Enum (string)


**Allowed Values:**
- `A`
- `E`

---

### Expiration

expiration type


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `daysToExpiration` | integer (int32) |  |  |
| `expiration` | string |  |  |
| `expirationType` | ExpirationType |  |  |
| `standard` | boolean |  |  |
| `settlementType` | SettlementType |  |  |
| `optionRoots` | string |  |  |

---

### ExpirationChain

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `status` | string |  |  |
| `expirationList` | array |  |  |

---

### ExpirationType

M for End Of Month Expiration Calendar Cycle. (To match the last business day of the month), Q for Quarterly expirations (last business day of the quarter month MAR/JUN/SEP/DEC), W for Weekly expiration (also called Friday Short Term Expirations) and S for Expires 3rd Friday of the month (also known as regular options).


**Type:** Enum (string)


**Allowed Values:**
- `M`
- `Q`
- `S`
- `W`

---

### ExtendedMarket

Quote data for extended hours


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `askPrice` | number (double) |  | Extended market ask price |
| `askSize` | integer (int32) |  | Extended market ask size |
| `bidPrice` | number (double) |  | Extended market bid price |
| `bidSize` | integer (int32) |  | Extended market bid size |
| `lastPrice` | number (double) |  | Extended market last price |
| `lastSize` | integer (int32) |  | Regular market last size |
| `mark` | number (double) |  | mark price |
| `quoteTime` | integer (int64) |  | Extended market quote time in milliseconds since Epoch |
| `totalVolume` | number (int64) |  | Total volume |
| `tradeTime` | integer (int64) |  | Extended market trade time in milliseconds since Epoch |

---

### ForexResponse

Quote info of Forex security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `assetMainType` | AssetMainType |  |  |
| `ssid` | integer (int64) |  | SSID of instrument |
| `symbol` | string |  | Symbol of instrument |
| `realtime` | boolean |  | is quote realtime |
| `quote` | QuoteForex |  |  |
| `reference` | ReferenceForex |  |  |

---

### FundStrategy

FundStrategy "A" - Active "L" - Leveraged "P" - Passive "Q" - Quantitative "S" - Short


**Type:** Enum (string)


**Allowed Values:**
- `A`
- `L`
- `P`
- `Q`
- `S`
- `None`

---

### Fundamental

Fundamentals of a security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `avg10DaysVolume` | number (double) |  | Average 10 day volume |
| `avg1YearVolume` | number (double) |  | Average 1 day volume |
| `declarationDate` | string (date-time) |  | Declaration date in yyyy-mm-ddThh:mm:ssZ |
| `divAmount` | number (double) |  | Dividend Amount |
| `divExDate` | string (yyyy-MM-dd'T'HH:mm:ssZ) |  | Dividend date in yyyy-mm-ddThh:mm:ssZ |
| `divFreq` | DivFreq |  |  |
| `divPayAmount` | number (double) |  | Dividend Pay Amount |
| `divPayDate` | string (date-time) |  | Dividend pay date in yyyy-mm-ddThh:mm:ssZ |
| `divYield` | number (double) |  | Dividend yield |
| `eps` | number (double) |  | Earnings per Share |
| `fundLeverageFactor` | number (double) |  | Fund Leverage Factor + > 0 <- |
| `fundStrategy` | FundStrategy |  |  |
| `nextDivExDate` | string (date-time) |  | Next Dividend date |
| `nextDivPayDate` | string (date-time) |  | Next Dividend pay date |
| `peRatio` | number (double) |  | P/E Ratio |

---

### FundamentalInst

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `symbol` | string |  |  |
| `high52` | number (double) |  |  |
| `low52` | number (double) |  |  |
| `dividendAmount` | number (double) |  |  |
| `dividendYield` | number (double) |  |  |
| `dividendDate` | string |  |  |
| `peRatio` | number (double) |  |  |
| `pegRatio` | number (double) |  |  |
| `pbRatio` | number (double) |  |  |
| `prRatio` | number (double) |  |  |
| `pcfRatio` | number (double) |  |  |
| `grossMarginTTM` | number (double) |  |  |
| `grossMarginMRQ` | number (double) |  |  |
| `netProfitMarginTTM` | number (double) |  |  |
| `netProfitMarginMRQ` | number (double) |  |  |
| `operatingMarginTTM` | number (double) |  |  |
| `operatingMarginMRQ` | number (double) |  |  |
| `returnOnEquity` | number (double) |  |  |
| `returnOnAssets` | number (double) |  |  |
| `returnOnInvestment` | number (double) |  |  |
| `quickRatio` | number (double) |  |  |
| `currentRatio` | number (double) |  |  |
| `interestCoverage` | number (double) |  |  |
| `totalDebtToCapital` | number (double) |  |  |
| `ltDebtToEquity` | number (double) |  |  |
| `totalDebtToEquity` | number (double) |  |  |
| `epsTTM` | number (double) |  |  |
| `epsChangePercentTTM` | number (double) |  |  |
| `epsChangeYear` | number (double) |  |  |
| `epsChange` | number (double) |  |  |
| `revChangeYear` | number (double) |  |  |
| `revChangeTTM` | number (double) |  |  |
| `revChangeIn` | number (double) |  |  |
| `sharesOutstanding` | number (double) |  |  |
| `marketCapFloat` | number (double) |  |  |
| `marketCap` | number (double) |  |  |
| `bookValuePerShare` | number (double) |  |  |
| `shortIntToFloat` | number (double) |  |  |
| `shortIntDayToCover` | number (double) |  |  |
| `divGrowthRate3Year` | number (double) |  |  |
| `dividendPayAmount` | number (double) |  |  |
| `dividendPayDate` | string |  |  |
| `beta` | number (double) |  |  |
| `vol1DayAvg` | number (double) |  |  |
| `vol10DayAvg` | number (double) |  |  |
| `vol3MonthAvg` | number (double) |  |  |
| `avg10DaysVolume` | integer (int64) |  |  |
| `avg1DayVolume` | integer (int64) |  |  |
| `avg3MonthVolume` | integer (int64) |  |  |
| `declarationDate` | string |  |  |
| `dividendFreq` | integer (int32) |  |  |
| `eps` | number (double) |  |  |
| `corpactionDate` | string |  |  |
| `dtnVolume` | integer (int64) |  |  |
| `nextDividendPayDate` | string |  |  |
| `nextDividendDate` | string |  |  |
| `fundLeverageFactor` | number (double) |  |  |
| `fundStrategy` | string |  |  |

---

### FutureOptionResponse

Quote info of Future Option security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `assetMainType` | AssetMainType |  |  |
| `ssid` | integer (int64) |  | SSID of instrument |
| `symbol` | string |  | Symbol of instrument |
| `realtime` | boolean |  | is quote realtime |
| `quote` | QuoteFutureOption |  |  |
| `reference` | ReferenceFutureOption |  |  |

---

### FutureResponse

Quote info of Future security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `assetMainType` | AssetMainType |  |  |
| `ssid` | integer (int64) |  | SSID of instrument |
| `symbol` | string |  | Symbol of instrument |
| `realtime` | boolean |  | is quote realtime |
| `quote` | QuoteFuture |  |  |
| `reference` | ReferenceFuture |  |  |

---

### Hours

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `date` | string |  |  |
| `marketType` | string<br>Values: `BOND`, `EQUITY`, `ETF`, `EXTENDED`, `FOREX`, `FUTURE`, `FUTURE_OPTION`, `FUNDAMENTAL`, `INDEX`, `INDICATOR`... |  |  |
| `exchange` | string |  |  |
| `category` | string |  |  |
| `product` | string |  |  |
| `productName` | string |  |  |
| `isOpen` | boolean |  |  |
| `sessionHours` | object |  |  |

---

### IndexResponse

Quote info of Index security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `assetMainType` | AssetMainType |  |  |
| `ssid` | integer (int64) |  | SSID of instrument |
| `symbol` | string |  | Symbol of instrument |
| `realtime` | boolean |  | is quote realtime |
| `quote` | QuoteIndex |  |  |
| `reference` | ReferenceIndex |  |  |

---

### Instrument

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `cusip` | string |  |  |
| `symbol` | string |  |  |
| `description` | string |  |  |
| `exchange` | string |  |  |
| `assetType` | string<br>Values: `BOND`, `EQUITY`, `ETF`, `EXTENDED`, `FOREX`, `FUTURE`, `FUTURE_OPTION`, `FUNDAMENTAL`, `INDEX`, `INDICATOR`... |  |  |
| `type` | string<br>Values: `BOND`, `EQUITY`, `ETF`, `EXTENDED`, `FOREX`, `FUTURE`, `FUTURE_OPTION`, `FUNDAMENTAL`, `INDEX`, `INDICATOR`... |  |  |

---

### InstrumentResponse

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `cusip` | string |  |  |
| `symbol` | string |  |  |
| `description` | string |  |  |
| `exchange` | string |  |  |
| `assetType` | string<br>Values: `BOND`, `EQUITY`, `ETF`, `EXTENDED`, `FOREX`, `FUTURE`, `FUTURE_OPTION`, `FUNDAMENTAL`, `INDEX`, `INDICATOR`... |  |  |
| `bondFactor` | string |  |  |
| `bondMultiplier` | string |  |  |
| `bondPrice` | number |  |  |
| `fundamental` | FundamentalInst |  |  |
| `instrumentInfo` | Instrument |  |  |
| `bondInstrumentInfo` | Bond |  |  |
| `type` | string<br>Values: `BOND`, `EQUITY`, `ETF`, `EXTENDED`, `FOREX`, `FUTURE`, `FUTURE_OPTION`, `FUNDAMENTAL`, `INDEX`, `INDICATOR`... |  |  |

---

### Interval

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `start` | string |  |  |
| `end` | string |  |  |

---

### MutualFundAssetSubType

Asset Sub Type (only there if applicable)


**Type:** Enum (string)


**Allowed Values:**
- `OEF`
- `CEF`
- `MMF`
- `None`

---

### MutualFundResponse

Quote info of MutualFund security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `assetMainType` | AssetMainType |  |  |
| `assetSubType` | MutualFundAssetSubType |  |  |
| `ssid` | integer (int64) |  | SSID of instrument |
| `symbol` | string |  | Symbol of instrument |
| `realtime` | boolean |  | is quote realtime |
| `fundamental` | Fundamental |  |  |
| `quote` | QuoteMutualFund |  |  |
| `reference` | ReferenceMutualFund |  |  |

---

### OptionChain

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `symbol` | string |  |  |
| `status` | string |  |  |
| `underlying` | Underlying |  |  |
| `strategy` | string<br>Values: `SINGLE`, `ANALYTICAL`, `COVERED`, `VERTICAL`, `CALENDAR`, `STRANGLE`, `STRADDLE`, `BUTTERFLY`, `CONDOR`, `DIAGONAL`... |  |  |
| `interval` | number (double) |  |  |
| `isDelayed` | boolean |  |  |
| `isIndex` | boolean |  |  |
| `daysToExpiration` | number (double) |  |  |
| `interestRate` | number (double) |  |  |
| `underlyingPrice` | number (double) |  |  |
| `volatility` | number (double) |  |  |
| `callExpDateMap` | object |  |  |
| `putExpDateMap` | object |  |  |

---

### OptionContract

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `putCall` | string<br>Values: `PUT`, `CALL` |  |  |
| `symbol` | string |  |  |
| `description` | string |  |  |
| `exchangeName` | string |  |  |
| `bidPrice` | number (double) |  |  |
| `askPrice` | number (double) |  |  |
| `lastPrice` | number (double) |  |  |
| `markPrice` | number (double) |  |  |
| `bidSize` | integer (int32) |  |  |
| `askSize` | integer (int32) |  |  |
| `lastSize` | integer (int32) |  |  |
| `highPrice` | number (double) |  |  |
| `lowPrice` | number (double) |  |  |
| `openPrice` | number (double) |  |  |
| `closePrice` | number (double) |  |  |
| `totalVolume` | integer (int32) |  |  |
| `tradeDate` | number (integer) |  |  |
| `quoteTimeInLong` | integer (int32) |  |  |
| `tradeTimeInLong` | integer (int32) |  |  |
| `netChange` | number (double) |  |  |
| `volatility` | number (double) |  |  |
| `delta` | number (double) |  |  |
| `gamma` | number (double) |  |  |
| `theta` | number (double) |  |  |
| `vega` | number (double) |  |  |
| `rho` | number (double) |  |  |
| `timeValue` | number (double) |  |  |
| `openInterest` | number (double) |  |  |
| `isInTheMoney` | boolean |  |  |
| `theoreticalOptionValue` | number (double) |  |  |
| `theoreticalVolatility` | number (double) |  |  |
| `isMini` | boolean |  |  |
| `isNonStandard` | boolean |  |  |
| `optionDeliverablesList` | array |  |  |
| `strikePrice` | number (double) |  |  |
| `expirationDate` | string |  |  |
| `daysToExpiration` | number (int) |  |  |
| `expirationType` | ExpirationType |  |  |
| `lastTradingDay` | number (long) |  |  |
| `multiplier` | number (double) |  |  |
| `settlementType` | SettlementType |  |  |
| `deliverableNote` | string |  |  |
| `isIndexOption` | boolean |  |  |
| `percentChange` | number (double) |  |  |
| `markChange` | number (double) |  |  |
| `markPercentChange` | number (double) |  |  |
| `isPennyPilot` | boolean |  |  |
| `intrinsicValue` | number (double) |  |  |
| `optionRoot` | string |  |  |

---

### OptionContractMap

---

### OptionDeliverables

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `symbol` | string |  |  |
| `assetType` | string |  |  |
| `deliverableUnits` | string |  |  |
| `currencyType` | string |  |  |

---

### OptionResponse

Quote info of Option security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `assetMainType` | AssetMainType |  |  |
| `ssid` | integer (int64) |  | SSID of instrument |
| `symbol` | string |  | Symbol of instrument |
| `realtime` | boolean |  | is quote realtime |
| `quote` | QuoteOption |  |  |
| `reference` | ReferenceOption |  |  |

---

### QuoteEquity

Quote data of Equity security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `52WeekHigh` | number (double) |  | Higest price traded in the past 12 months, or 52 weeks |
| `52WeekLow` | number (double) |  | Lowest price traded in the past 12 months, or 52 weeks |
| `askMICId` | string |  | ask MIC code |
| `askPrice` | number (double) |  | Current Best Ask Price |
| `askSize` | integer (int32) |  | Number of shares for ask |
| `askTime` | integer (int64) |  | Last ask time in milliseconds since Epoch |
| `bidMICId` | string |  | bid MIC code |
| `bidPrice` | number (double) |  | Current Best Bid Price |
| `bidSize` | integer (int32) |  | Number of shares for bid |
| `bidTime` | integer (int64) |  | Last bid time in milliseconds since Epoch |
| `closePrice` | number (double) |  | Previous day's closing price |
| `highPrice` | number (double) |  | Day's high trade price |
| `lastMICId` | string |  | Last MIC Code |
| `lastPrice` | number (double) |  |  |
| `lastSize` | integer (int32) |  | Number of shares traded with last trade |
| `lowPrice` | number (double) |  | Day's low trade price |
| `mark` | number (double) |  | Mark price |
| `markChange` | number (double) |  | Mark Price change |
| `markPercentChange` | number (double) |  | Mark Price percent change |
| `netChange` | number (double) |  | Current Last-Prev Close |
| `netPercentChange` | number (double) |  | Net Percentage Change |
| `openPrice` | number (double) |  | Price at market open |
| `quoteTime` | integer (int64) |  | Last quote time in milliseconds since Epoch |
| `securityStatus` | string |  | Status of security |
| `totalVolume` | integer (int64) |  | Aggregated shares traded throughout the day, including pre/post market hours. |
| `tradeTime` | integer (int64) |  | Last trade time in milliseconds since Epoch |
| `volatility` | number (double) |  | Option Risk/Volatility Measurement |

---

### QuoteError

Partial or Custom errors per request


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `invalidCusips` | array |  | list of invalid cusips from request |
| `invalidSSIDs` | array |  | list of invalid SSIDs from request |
| `invalidSymbols` | array |  | list of invalid symbols from request |

---

### QuoteForex

Quote data of Forex security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `52WeekHigh` | number (double) |  | Higest price traded in the past 12 months, or 52 weeks |
| `52WeekLow` | number (double) |  | Lowest price traded in the past 12 months, or 52 weeks |
| `askPrice` | number (double) |  | Current Best Ask Price |
| `askSize` | integer (int32) |  | Number of shares for ask |
| `bidPrice` | number (double) |  | Current Best Bid Price |
| `bidSize` | integer (int32) |  | Number of shares for bid |
| `closePrice` | number (double) |  | Previous day's closing price |
| `highPrice` | number (double) |  | Day's high trade price |
| `lastPrice` | number (double) |  |  |
| `lastSize` | integer (int32) |  | Number of shares traded with last trade |
| `lowPrice` | number (double) |  | Day's low trade price |
| `mark` | number (double) |  | Mark price |
| `netChange` | number (double) |  | Current Last-Prev Close |
| `netPercentChange` | number (double) |  | Net Percentage Change |
| `openPrice` | number (double) |  | Price at market open |
| `quoteTime` | integer (int64) |  | Last quote time in milliseconds since Epoch |
| `securityStatus` | string |  | Status of security |
| `tick` | number (double) |  | Tick Price |
| `tickAmount` | number (double) |  | Tick Amount |
| `totalVolume` | integer (int64) |  | Aggregated shares traded throughout the day, including pre/post market hours. |
| `tradeTime` | integer (int64) |  | Last trade time in milliseconds since Epoch |

---

### QuoteFuture

Quote data of Future security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `askMICId` | string |  | ask MIC code |
| `askPrice` | number (double) |  | Current Best Ask Price |
| `askSize` | integer (int32) |  | Number of shares for ask |
| `askTime` | integer (int64) |  | Last ask time in milliseconds since Epoch |
| `bidMICId` | string |  | bid MIC code |
| `bidPrice` | number (double) |  | Current Best Bid Price |
| `bidSize` | integer (int32) |  | Number of shares for bid |
| `bidTime` | integer (int64) |  | Last bid time in milliseconds since Epoch |
| `closePrice` | number (double) |  | Previous day's closing price |
| `futurePercentChange` | number (double) |  | Net Percentage Change |
| `highPrice` | number (double) |  | Day's high trade price |
| `lastMICId` | string |  | Last MIC Code |
| `lastPrice` | number (double) |  |  |
| `lastSize` | integer (int32) |  | Number of shares traded with last trade |
| `lowPrice` | number (double) |  | Day's low trade price |
| `mark` | number (double) |  | Mark price |
| `netChange` | number (double) |  | Current Last-Prev Close |
| `openInterest` | integer (int32) |  | Open interest |
| `openPrice` | number (double) |  | Price at market open |
| `quoteTime` | integer (int64) |  | Last quote time in milliseconds since Epoch |
| `quotedInSession` | boolean |  | quoted during trading session |
| `securityStatus` | string |  | Status of security |
| `settleTime` | integer (int64) |  | settlement time in milliseconds since Epoch |
| `tick` | number (double) |  | Tick Price |
| `tickAmount` | number (double) |  | Tick Amount |
| `totalVolume` | integer (int64) |  | Aggregated shares traded throughout the day, including pre/post market hours. |
| `tradeTime` | integer (int64) |  | Last trade time in milliseconds since Epoch |

---

### QuoteFutureOption

Quote data of Option security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `askMICId` | string |  | ask MIC code |
| `askPrice` | number (double) |  | Current Best Ask Price |
| `askSize` | integer (int32) |  | Number of shares for ask |
| `bidMICId` | string |  | bid MIC code |
| `bidPrice` | number (double) |  | Current Best Bid Price |
| `bidSize` | integer (int32) |  | Number of shares for bid |
| `closePrice` | number (double) |  | Previous day's closing price |
| `highPrice` | number (double) |  | Day's high trade price |
| `lastMICId` | string |  | Last MIC Code |
| `lastPrice` | number (double) |  |  |
| `lastSize` | integer (int32) |  | Number of shares traded with last trade |
| `lowPrice` | number (double) |  | Day's low trade price |
| `mark` | number (double) |  | Mark price |
| `markChange` | number (double) |  | Mark Price change |
| `netChange` | number (double) |  | Current Last-Prev Close |
| `netPercentChange` | number (double) |  | Net Percentage Change |
| `openInterest` | integer (int32) |  | Open Interest |
| `openPrice` | number (double) |  | Price at market open |
| `quoteTime` | integer (int64) |  | Last quote time in milliseconds since Epoch |
| `securityStatus` | string |  | Status of security |
| `settlemetPrice` | number (double) |  | Price at market open |
| `tick` | number (double) |  | Tick Price |
| `tickAmount` | number (double) |  | Tick Amount |
| `totalVolume` | integer (int64) |  | Aggregated shares traded throughout the day, including pre/post market hours. |
| `tradeTime` | integer (int64) |  | Last trade time in milliseconds since Epoch |

---

### QuoteIndex

Quote data of Index security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `52WeekHigh` | number (double) |  | Higest price traded in the past 12 months, or 52 weeks |
| `52WeekLow` | number (double) |  | Lowest price traded in the past 12 months, or 52 weeks |
| `closePrice` | number (double) |  | Previous day's closing price |
| `highPrice` | number (double) |  | Day's high trade price |
| `lastPrice` | number (double) |  |  |
| `lowPrice` | number (double) |  | Day's low trade price |
| `netChange` | number (double) |  | Current Last-Prev Close |
| `netPercentChange` | number (double) |  | Net Percentage Change |
| `openPrice` | number (double) |  | Price at market open |
| `securityStatus` | string |  | Status of security |
| `totalVolume` | integer (int64) |  | Aggregated shares traded throughout the day, including pre/post market hours. |
| `tradeTime` | integer (int64) |  | Last trade time in milliseconds since Epoch |

---

### QuoteMutualFund

Quote data of Mutual Fund security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `52WeekHigh` | number (double) |  | Higest price traded in the past 12 months, or 52 weeks |
| `52WeekLow` | number (double) |  | Lowest price traded in the past 12 months, or 52 weeks |
| `closePrice` | number (double) |  | Previous day's closing price |
| `nAV` | number (double) |  | Net Asset Value |
| `netChange` | number (double) |  | Current Last-Prev Close |
| `netPercentChange` | number (double) |  | Net Percentage Change |
| `securityStatus` | string |  | Status of security |
| `totalVolume` | integer (int64) |  | Aggregated shares traded throughout the day, including pre/post market hours. |
| `tradeTime` | integer (int64) |  | Last trade time in milliseconds since Epoch |

---

### QuoteOption

Quote data of Option security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `52WeekHigh` | number (double) |  | Higest price traded in the past 12 months, or 52 weeks |
| `52WeekLow` | number (double) |  | Lowest price traded in the past 12 months, or 52 weeks |
| `askPrice` | number (double) |  | Current Best Ask Price |
| `askSize` | integer (int32) |  | Number of shares for ask |
| `bidPrice` | number (double) |  | Current Best Bid Price |
| `bidSize` | integer (int32) |  | Number of shares for bid |
| `closePrice` | number (double) |  | Previous day's closing price |
| `delta` | number (double) |  | Delta Value |
| `gamma` | number (double) |  | Gamma Value |
| `highPrice` | number (double) |  | Day's high trade price |
| `indAskPrice` | number (double) |  | Indicative Ask Price applicable only for Indicative Option Symbols |
| `indBidPrice` | number (double) |  | Indicative Bid Price applicable only for Indicative Option Symbols |
| `indQuoteTime` | integer (int64) |  | Indicative Quote Time in milliseconds since Epoch applicable only for Indicative Option Symbols |
| `impliedYield` | number (double) |  | Implied Yield |
| `lastPrice` | number (double) |  |  |
| `lastSize` | integer (int32) |  | Number of shares traded with last trade |
| `lowPrice` | number (double) |  | Day's low trade price |
| `mark` | number (double) |  | Mark price |
| `markChange` | number (double) |  | Mark Price change |
| `markPercentChange` | number (double) |  | Mark Price percent change |
| `moneyIntrinsicValue` | number (double) |  | Money Intrinsic Value |
| `netChange` | number (double) |  | Current Last-Prev Close |
| `netPercentChange` | number (double) |  | Net Percentage Change |
| `openInterest` | number (double) |  | Open Interest |
| `openPrice` | number (double) |  | Price at market open |
| `quoteTime` | integer (int64) |  | Last quote time in milliseconds since Epoch |
| `rho` | number (double) |  | Rho Value |
| `securityStatus` | string |  | Status of security |
| `theoreticalOptionValue` | number (double) |  | Theoretical option Value |
| `theta` | number (double) |  | Theta Value |
| `timeValue` | number (double) |  | Time Value |
| `totalVolume` | integer (int64) |  | Aggregated shares traded throughout the day, including pre/post market hours. |
| `tradeTime` | integer (int64) |  | Last trade time in milliseconds since Epoch |
| `underlyingPrice` | number (double) |  | Underlying Price |
| `vega` | number (double) |  | Vega Value |
| `volatility` | number (double) |  | Option Risk/Volatility Measurement |

---

### QuoteRequest

Request one or more quote data in POST body


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `cusips` | array |  | List of cusip, max of 500 of symbols+cusip+ssids |
| `fields` | string |  | comma separated list of nodes in each quote<br/> possible values are quote,fundamental,reference,extended,regular. Dont send this attribute for full response. |
| `ssids` | array |  | List of Schwab securityid[SSID], max of 500 of symbols+cusip+ssids |
| `symbols` | array |  | List of symbols, max of 500 of symbols+cusip+ssids |
| `realtime` | boolean<br>Values: `True`, `False` |  | Get realtime quotes and skip entitlement check |
| `indicative` | boolean<br>Values: `True`, `False` |  | Include indicative symbol quotes for all ETF symbols in request. If ETF symbol ABC is in request and indicative=true API will return quotes for ABC and its corresponding indicative quote for $ABC.IV |

---

### QuoteResponse

a (symbol, QuoteResponse) map. `SCHW`is an example key


---

### QuoteResponseObject

---

### QuoteType

NBBO - realtime, NFL - Non-fee liable quote.


**Type:** Enum (string)


**Allowed Values:**
- `NBBO`
- `NFL`
- `None`

---

### ReferenceEquity

Reference data of Equity security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `cusip` | string |  | CUSIP of Instrument |
| `description` | string |  | Description of Instrument |
| `exchange` | string |  | Exchange Code |
| `exchangeName` | string |  | Exchange Name |
| `fsiDesc` | string |  | FSI Desc |
| `htbQuantity` | integer (int32) |  | Hard to borrow quantity. |
| `htbRate` | number (double) |  | Hard to borrow rate. |
| `isHardToBorrow` | boolean |  | is Hard to borrow security. |
| `isShortable` | boolean |  | is shortable security. |
| `otcMarketTier` | string |  | OTC Market Tier |

---

### ReferenceForex

Reference data of Forex security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `description` | string |  | Description of Instrument |
| `exchange` | string |  | Exchange Code |
| `exchangeName` | string |  | Exchange Name |
| `isTradable` | boolean |  | is FOREX tradable |
| `marketMaker` | string |  | Market marker |
| `product` | string |  | Product name |
| `tradingHours` | string |  | Trading hours |

---

### ReferenceFuture

Reference data of Future security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `description` | string |  | Description of Instrument |
| `exchange` | string |  | Exchange Code |
| `exchangeName` | string |  | Exchange Name |
| `futureActiveSymbol` | string |  | Active symbol |
| `futureExpirationDate` | number (int64) |  | Future expiration date in milliseconds since epoch |
| `futureIsActive` | boolean |  | Future is active |
| `futureMultiplier` | number (double) |  | Future multiplier |
| `futurePriceFormat` | string |  | Price format |
| `futureSettlementPrice` | number (double) |  | Future Settlement Price |
| `futureTradingHours` | string |  | Trading Hours |
| `product` | string |  | Futures product symbol |

---

### ReferenceFutureOption

Reference data of Future Option security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `contractType` | ContractType |  |  |
| `description` | string |  | Description of Instrument |
| `exchange` | string |  | Exchange Code |
| `exchangeName` | string |  | Exchange Name |
| `multiplier` | number (double) |  | Option multiplier |
| `expirationDate` | integer (int64) |  | date of expiration in long |
| `expirationStyle` | string |  | Style of expiration |
| `strikePrice` | number (double) |  | Strike Price |
| `underlying` | string |  | A company, index or fund name |

---

### ReferenceIndex

Reference data of Index security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `description` | string |  | Description of Instrument |
| `exchange` | string |  | Exchange Code |
| `exchangeName` | string |  | Exchange Name |

---

### ReferenceMutualFund

Reference data of MutualFund security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `cusip` | string |  | CUSIP of Instrument |
| `description` | string |  | Description of Instrument |
| `exchange` | string |  | Exchange Code |
| `exchangeName` | string |  | Exchange Name |

---

### ReferenceOption

Reference data of Option security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `contractType` | ContractType |  |  |
| `cusip` | string |  | CUSIP of Instrument |
| `daysToExpiration` | integer (int32) |  | Days to Expiration |
| `deliverables` | string |  | Unit of trade |
| `description` | string |  | Description of Instrument |
| `exchange` | string |  | Exchange Code |
| `exchangeName` | string |  | Exchange Name |
| `exerciseType` | ExerciseType |  |  |
| `expirationDay` | integer (int32) |  | Expiration Day |
| `expirationMonth` | integer (int32) |  | Expiration Month |
| `expirationType` | ExpirationType |  |  |
| `expirationYear` | integer (int32) |  | Expiration Year |
| `isPennyPilot` | boolean |  | Is this contract part of the Penny Pilot program |
| `lastTradingDay` | integer (int64) |  | milliseconds since epoch |
| `multiplier` | number (double) |  | Option multiplier |
| `settlementType` | SettlementType |  |  |
| `strikePrice` | number (double) |  | Strike Price |
| `underlying` | string |  | A company, index or fund name |

---

### RegularMarket

Market info of security


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `regularMarketLastPrice` | number (double) |  | Regular market last price |
| `regularMarketLastSize` | integer (int32) |  | Regular market last size |
| `regularMarketNetChange` | number (double) |  | Regular market net change |
| `regularMarketPercentChange` | number (double) |  | Regular market percent change |
| `regularMarketTradeTime` | integer (int64) |  | Regular market trade time in milliseconds since Epoch |

---

### Screener

Security info of most moved with in an index


**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `change` | number (double) |  | percent or value changed, by default its percent changed |
| `description` | string |  | Name of security |
| `direction` | string<br>Values: `up`, `down` |  |  |
| `last` | number (double) |  | what was last quoted price |
| `symbol` | string |  | schwab security symbol |
| `totalVolume` | integer (int64) |  |  |

---

### SettlementType

option contract settlement type AM or PM


**Type:** Enum (string)


**Allowed Values:**
- `A`
- `P`

---

### Underlying

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `ask` | number (double) |  |  |
| `askSize` | integer (int32) |  |  |
| `bid` | number (double) |  |  |
| `bidSize` | integer (int32) |  |  |
| `change` | number (double) |  |  |
| `close` | number (double) |  |  |
| `delayed` | boolean |  |  |
| `description` | string |  |  |
| `exchangeName` | string<br>Values: `IND`, `ASE`, `NYS`, `NAS`, `NAP`, `PAC`, `OPR`, `BATS` |  |  |
| `fiftyTwoWeekHigh` | number (double) |  |  |
| `fiftyTwoWeekLow` | number (double) |  |  |
| `highPrice` | number (double) |  |  |
| `last` | number (double) |  |  |
| `lowPrice` | number (double) |  |  |
| `mark` | number (double) |  |  |
| `markChange` | number (double) |  |  |
| `markPercentChange` | number (double) |  |  |
| `openPrice` | number (double) |  |  |
| `percentChange` | number (double) |  |  |
| `quoteTime` | integer (int64) |  |  |
| `symbol` | string |  |  |
| `totalVolume` | integer (int64) |  |  |
| `tradeTime` | integer (int64) |  |  |

---
