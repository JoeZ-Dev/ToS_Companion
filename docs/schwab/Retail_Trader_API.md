# Trader API - Account Access and User Preferences

**Version:** 1.0.0  
**OpenAPI Version:** 3.0.1

Schwab Trader API access to Account, Order entry and User Preferences

## Base URL

```
https://api.schwabapi.com/trader/v1
```

## Authentication

### oauth

**Type:** oauth2  
**Flow:** authorizationCode  
**Authorization URL:** `https://api.schwabapi.com/v1/oauth/authorize?response_type=code&client_id=1wzwOrhivb2PkR1UCAUVTKYqC4MTNYlj&scope=readonly&redirect_uri=https://developer.schwab.com/oauth2-redirect.html`  
**Token URL:** `https://api.schwabapi.com/v1/oauth/token`  

**Scopes:**

## Table of Contents

- [Endpoints](#endpoints)
  - [/accounts](#accounts)
  - [/accounts/accountNumbers](#accountsaccountnumbers)
  - [/accounts/{accountNumber}](#accountsaccountnumber)
  - [/accounts/{accountNumber}/orders](#accountsaccountnumberorders)
  - [/accounts/{accountNumber}/orders/{orderId}](#accountsaccountnumberordersorderid)
  - [/accounts/{accountNumber}/previewOrder](#accountsaccountnumberprevieworder)
  - [/accounts/{accountNumber}/transactions](#accountsaccountnumbertransactions)
  - [/accounts/{accountNumber}/transactions/{transactionId}](#accountsaccountnumbertransactionstransactionid)
  - [/orders](#orders)
  - [/userPreference](#userpreference)
- [Schemas](#schemas)

## Endpoints

### /accounts

<a name="accounts"></a>

#### GET

**Summary:** Get linked account(s) balances and positions for the logged in user.  
**Description:** All the linked account information for the user logged in. The
balances on these accounts are displayed by default however the positions
on these accounts will be displayed based on the "positions" flag.  
**Operation ID:** `getAccounts`  
**Tags:** Accounts  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `fields` | query |  | string | This allows one to determine which fields they want returned. Possible value in this String can be:
<br><code>positions</code><br> Example:<br><code>fields=positions</code> |

**Responses:**

**200** - List of valid "accounts", matching the provided input parameters.  
  - Content-Type: `application/json`
  - Schema: Array of [Account](#account)

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

### /accounts/accountNumbers

<a name="accountsaccountnumbers"></a>

#### GET

**Summary:** Get list of account numbers and their encrypted values  
**Description:** Account numbers in plain text cannot be used outside of headers or request/response bodies. As the first step consumers must invoke this service to retrieve the list of plain text/encrypted value pairs, and use encrypted account values for all subsequent calls for any accountNumber request.  
**Operation ID:** `getAccountNumbers`  
**Tags:** Accounts  

**Responses:**

**200** - List of valid "accounts", matching the provided input parameters.  
  - Content-Type: `application/json`
  - Schema: Array of [AccountNumberHash](#accountnumberhash)

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

### /accounts/{accountNumber}

<a name="accountsaccountnumber"></a>

#### GET

**Summary:** Get a specific account balance and positions for the logged in user.  
**Description:** Specific account information with balances and positions.
The balance information on these accounts is displayed by default but
Positions will be returned based on the "positions" flag.  
**Operation ID:** `getAccount`  
**Tags:** Accounts  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `accountNumber` | path | ✓ | string | The encrypted ID of the account |
| `fields` | query |  | string | This allows one to determine
which fields they want returned. Possible values in this String can be:
<br><code>positions</code><br> Example:<br><code>fields=positions</code> |

**Responses:**

**200** - A valid account, matching the provided input parameters  
  - Content-Type: `application/json`
  - Schema: [Account](#account)

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

### /accounts/{accountNumber}/orders

<a name="accountsaccountnumberorders"></a>

#### GET

**Summary:** Get all orders for a specific account.  
**Description:** All orders for a specific account. Orders retrieved can be filtered based on input parameters below. Maximum date range is 1 year.  
**Operation ID:** `getOrdersByPathParam`  
**Tags:** Orders  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `accountNumber` | path | ✓ | string | The encrypted ID of the account |
| `maxResults` | query |  | integer | The max number of orders to retrieve. Default is 3000. |
| `fromEnteredTime` | query | ✓ | string | Specifies that no orders entered before this time should be returned.
Valid ISO-8601 formats are :<br> <code>yyyy-MM-dd'T'HH:mm:ss.SSSZ</code>  Example fromEnteredTime is '2024-03-29T00:00:00.000Z'.
'toEnteredTime' must also be set. |
| `toEnteredTime` | query | ✓ | string | Specifies that no orders entered after this time should be returned.Valid
ISO-8601 formats are :<br> <code>yyyy-MM-dd'T'HH:mm:ss.SSSZ</code>.  Example toEnteredTime is '2024-04-28T23:59:59.000Z'.
'fromEnteredTime' must also be set. |
| `status` | query |  | apiOrderStatus | Specifies that only orders of this status should be returned. |

**Responses:**

**200** - A List of orders for the account, matching the provided input parameters  
  - Content-Type: `application/json`
  - Schema: Array of [Order](#order)

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

#### POST

**Summary:** Place order for a specific account.  
**Description:** Place an order for a specific account.  
**Operation ID:** `placeOrder`  
**Tags:** Orders  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `accountNumber` | path | ✓ | string | The encrypted ID of the account |

**Request Body:**

The new Order Object.

**Content-Type:** `application/json`

**Schema:** [OrderRequest](#orderrequest)

**Responses:**

**201** - Empty response body if an order was successfully placed/created.  

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

### /accounts/{accountNumber}/orders/{orderId}

<a name="accountsaccountnumberordersorderid"></a>

#### GET

**Summary:** Get a specific order by its ID, for a specific account  
**Description:** Get a specific order by its ID, for a specific account  
**Operation ID:** `getOrder`  
**Tags:** Orders  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `accountNumber` | path | ✓ | string | The encrypted ID of the account |
| `orderId` | path | ✓ | integer | The ID of the order being retrieved. |

**Responses:**

**200** - An order object, matching the input parameters  
  - Content-Type: `application/json`
  - Schema: [Order](#order)

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

#### DELETE

**Summary:** Cancel an order for a specific account  
**Description:** Cancel a specific order for a specific account<br>  
**Operation ID:** `cancelOrder`  
**Tags:** Orders  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `accountNumber` | path | ✓ | string | The encrypted ID of the account |
| `orderId` | path | ✓ | integer | The ID of the order being cancelled |

**Responses:**

**200** - Empty response body if an order was successfully canceled.  

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

#### PUT

**Summary:** Replace order for a specific account  
**Description:** Replace an existing order for an account. The existing order will be replaced by the new               order. Once replaced, the old order will be canceled and a new order will be created.  
**Operation ID:** `replaceOrder`  
**Tags:** Orders  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `accountNumber` | path | ✓ | string | The encrypted ID of the account |
| `orderId` | path | ✓ | integer | The ID of the order being retrieved. |

**Request Body:**

The Order Object.

**Content-Type:** `application/json`

**Schema:** [OrderRequest](#orderrequest)

**Responses:**

**201** - Empty response body if an order was successfully replaced/created.  

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

### /accounts/{accountNumber}/previewOrder

<a name="accountsaccountnumberprevieworder"></a>

#### POST

**Summary:** Preview order for a specific account.  
**Description:** Preview an order for a specific account.  
**Operation ID:** `previewOrder`  
**Tags:** Orders  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `accountNumber` | path | ✓ | string | The encrypted ID of the account |

**Request Body:**

The Order Object.

**Content-Type:** `application/json`

**Schema:** [PreviewOrder](#previeworder)

**Responses:**

**200** - An order object, matching the input parameters  
  - Content-Type: `application/json`
  - Schema: [PreviewOrder](#previeworder)

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

### /accounts/{accountNumber}/transactions

<a name="accountsaccountnumbertransactions"></a>

#### GET

**Summary:** Get all transactions information for a specific account.  
**Description:** All transactions for a specific account. Maximum number of transactions in response is 3000. Maximum date range is 1 year.  
**Operation ID:** `getTransactionsByPathParam`  
**Tags:** Transactions  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `accountNumber` | path | ✓ | string | The encrypted ID of the account |
| `startDate` | query | ✓ | string | Specifies that no transactions entered before this time should be returned.
Valid ISO-8601 formats are :<br> <code>yyyy-MM-dd'T'HH:mm:ss.SSSZ</code> .  Example start date is '2024-03-28T21:10:42.000Z'. The 'endDate' must also be set. |
| `endDate` | query | ✓ | string | Specifies that no transactions entered after this time should be returned.Valid
ISO-8601 formats are :<br> <code>yyyy-MM-dd'T'HH:mm:ss.SSSZ</code>. Example start date is '2024-05-10T21:10:42.000Z'.
The 'startDate' must also be set. |
| `symbol` | query |  | string | It filters all the transaction activities based on the symbol specified. <u>NOTE:</u> If there is any special character in the symbol, please send th encoded value. |
| `types` | query | ✓ | TransactionType | Specifies that only transactions of this status should be returned. |

**Responses:**

**200** - A List of orders for the account, matching the provided input
parameters  
  - Content-Type: `application/json`
  - Schema: Array of [Transaction](#transaction)

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

### /accounts/{accountNumber}/transactions/{transactionId}

<a name="accountsaccountnumbertransactionstransactionid"></a>

#### GET

**Summary:** Get specific transaction information for a specific account  
**Description:** Get specific transaction information for a specific account  
**Operation ID:** `getTransactionsById`  
**Tags:** Transactions  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `accountNumber` | path | ✓ | string | The encrypted ID of the account |
| `transactionId` | path | ✓ | integer | The ID of the transaction being retrieved. |

**Responses:**

**200** - A List of orders for the account, matching the provided input parameters  
  - Content-Type: `application/json`
  - Schema: Array of [Transaction](#transaction)

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

### /orders

<a name="orders"></a>

#### GET

**Summary:** Get all orders for all accounts  
**Description:** Get all orders for all accounts<br>  
**Operation ID:** `getOrdersByQueryParam`  
**Tags:** Orders  

**Parameters:**

| Name | Location | Required | Type | Description |
|------|----------|----------|------|-------------|
| `maxResults` | query |  | integer | The max number of orders to retrieve. Default is 3000. |
| `fromEnteredTime` | query | ✓ | string | Specifies that no orders entered before this time should be returned. Valid ISO-8601 formats are-
yyyy-MM-dd'T'HH:mm:ss.SSSZ Date must be within 60 days from today's date.
'toEnteredTime' must also be set. |
| `toEnteredTime` | query | ✓ | string | Specifies that no orders entered after this time should be returned.Valid ISO-8601 formats are -
yyyy-MM-dd'T'HH:mm:ss.SSSZ. 'fromEnteredTime' must also be set. |
| `status` | query |  | apiOrderStatus | Specifies that only orders of this status should be returned. |

**Responses:**

**200** - A List of orders for the specified account or if its not mentioned,
for all the linked accounts, matching the provided input parameters.  
  - Content-Type: `application/json`
  - Schema: Array of [Order](#order)

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

### /userPreference

<a name="userpreference"></a>

#### GET

**Summary:** Get user preference information for the logged in user.  
**Description:** Get user preference information for the logged in user.  
**Operation ID:** `getUserPreference`  
**Tags:** UserPreference  

**Responses:**

**200** - List of user preference values.  
  - Content-Type: `application/json`
  - Schema: Array of [UserPreference](#userpreference)

**400** - No description  

**401** - No description  

**403** - No description  

**404** - No description  

**500** - No description  

**503** - No description  

---

## Schemas

<a name="schemas"></a>

### APIRuleAction

**Type:** Enum (string)


**Allowed Values:**
- `ACCEPT`
- `ALERT`
- `REJECT`
- `REVIEW`
- `UNKNOWN`

---

### Account

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `securitiesAccount` | SecuritiesAccount |  |  |

---

### AccountAPIOptionDeliverable

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `symbol` | string (int64) |  |  |
| `deliverableUnits` | number (double) |  |  |
| `apiCurrencyType` | string<br>Values: `USD`, `CAD`, `EUR`, `JPY` |  |  |
| `assetType` | assetType |  |  |

---

### AccountCashEquivalent

**Composed of:**

- AccountsBaseInstrument

---

### AccountEquity

**Composed of:**

- AccountsBaseInstrument

---

### AccountFixedIncome

**Composed of:**

- AccountsBaseInstrument

---

### AccountMutualFund

**Composed of:**

- AccountsBaseInstrument

---

### AccountNumberHash

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `accountNumber` | string |  |  |
| `hashValue` | string |  |  |

---

### AccountOption

**Composed of:**

- AccountsBaseInstrument

---

### AccountsBaseInstrument

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `assetType` | string<br>Values: `EQUITY`, `OPTION`, `INDEX`, `MUTUAL_FUND`, `CASH_EQUIVALENT`, `FIXED_INCOME`, `CURRENCY`, `COLLECTIVE_INVESTMENT` | ✓ |  |
| `cusip` | string |  |  |
| `symbol` | string |  |  |
| `description` | string |  |  |
| `instrumentId` | integer (int64) |  |  |
| `netChange` | number (double) |  |  |

---

### AccountsInstrument

**One of the following types:**

1. AccountCashEquivalent
2. AccountEquity
3. AccountFixedIncome
4. AccountMutualFund
5. AccountOption

---

### CashAccount

**Composed of:**

- SecuritiesAccountBase

---

### CashBalance

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `cashAvailableForTrading` | number (double) |  |  |
| `cashAvailableForWithdrawal` | number (double) |  |  |
| `cashCall` | number (double) |  |  |
| `longNonMarginableMarketValue` | number (double) |  |  |
| `totalCash` | number (double) |  |  |
| `cashDebitCallValue` | number (double) |  |  |
| `unsettledCash` | number (double) |  |  |

---

### CashInitialBalance

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `accruedInterest` | number (double) |  |  |
| `cashAvailableForTrading` | number (double) |  |  |
| `cashAvailableForWithdrawal` | number (double) |  |  |
| `cashBalance` | number (double) |  |  |
| `bondValue` | number (double) |  |  |
| `cashReceipts` | number (double) |  |  |
| `liquidationValue` | number (double) |  |  |
| `longOptionMarketValue` | number (double) |  |  |
| `longStockValue` | number (double) |  |  |
| `moneyMarketFund` | number (double) |  |  |
| `mutualFundValue` | number (double) |  |  |
| `shortOptionMarketValue` | number (double) |  |  |
| `shortStockValue` | number (double) |  |  |
| `isInCall` | number (double) |  |  |
| `unsettledCash` | number (double) |  |  |
| `cashDebitCallValue` | number (double) |  |  |
| `pendingDeposits` | number (double) |  |  |
| `accountValue` | number (double) |  |  |

---

### CollectiveInvestment

**Composed of:**

- TransactionBaseInstrument

---

### Commission

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `commissionLegs` | array |  |  |

---

### CommissionAndFee

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `commission` | Commission |  |  |
| `fee` | Fees |  |  |
| `trueCommission` | Commission |  |  |

---

### CommissionLeg

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `commissionValues` | array |  |  |

---

### CommissionValue

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `value` | number (double) |  |  |
| `type` | FeeType |  |  |

---

### Currency

**Composed of:**

- TransactionBaseInstrument

---

### DateParam

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `date` | string |  | Valid ISO-8601 format is :<br> <code>yyyy-MM-dd'T'HH:mm:ss.SSSZ</code> |

---

### ExecutionLeg

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `legId` | integer (int64) |  |  |
| `price` | number (double) |  |  |
| `quantity` | number (double) |  |  |
| `mismarkedQuantity` | number (double) |  |  |
| `instrumentId` | integer (int64) |  |  |
| `time` | string (date-time) |  |  |

---

### FeeLeg

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `feeValues` | array |  |  |

---

### FeeType

**Type:** Enum (string)


**Allowed Values:**
- `COMMISSION`
- `SEC_FEE`
- `STR_FEE`
- `R_FEE`
- `CDSC_FEE`
- `OPT_REG_FEE`
- `ADDITIONAL_FEE`
- `MISCELLANEOUS_FEE`
- `FTT`
- `FUTURES_CLEARING_FEE`
- `FUTURES_DESK_OFFICE_FEE`
- `FUTURES_EXCHANGE_FEE`
- `FUTURES_GLOBEX_FEE`
- `FUTURES_NFA_FEE`
- `FUTURES_PIT_BROKERAGE_FEE`
- `FUTURES_TRANSACTION_FEE`
- `LOW_PROCEEDS_COMMISSION`
- `BASE_CHARGE`
- `GENERAL_CHARGE`
- `GST_FEE`
- `TAF_FEE`
- `INDEX_OPTION_FEE`
- `TEFRA_TAX`
- `STATE_TAX`
- `UNKNOWN`

---

### FeeValue

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `value` | number (double) |  |  |
| `type` | FeeType |  |  |

---

### Fees

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `feeLegs` | array |  |  |

---

### Forex

**Composed of:**

- TransactionBaseInstrument

---

### Future

**Composed of:**

- TransactionInstrument

---

### Index

**Composed of:**

- TransactionInstrument

---

### MarginAccount

**Composed of:**

- SecuritiesAccountBase

---

### MarginBalance

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `availableFunds` | number (double) |  |  |
| `availableFundsNonMarginableTrade` | number (double) |  |  |
| `buyingPower` | number (double) |  |  |
| `buyingPowerNonMarginableTrade` | number (double) |  |  |
| `dayTradingBuyingPower` | number (double) |  |  |
| `dayTradingBuyingPowerCall` | number (double) |  |  |
| `equity` | number (double) |  |  |
| `equityPercentage` | number (double) |  |  |
| `longMarginValue` | number (double) |  |  |
| `maintenanceCall` | number (double) |  |  |
| `maintenanceRequirement` | number (double) |  |  |
| `marginBalance` | number (double) |  |  |
| `regTCall` | number (double) |  |  |
| `shortBalance` | number (double) |  |  |
| `shortMarginValue` | number (double) |  |  |
| `sma` | number (double) |  |  |
| `isInCall` | number (double) |  |  |
| `stockBuyingPower` | number (double) |  |  |
| `optionBuyingPower` | number (double) |  |  |

---

### MarginInitialBalance

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `accruedInterest` | number (double) |  |  |
| `availableFundsNonMarginableTrade` | number (double) |  |  |
| `bondValue` | number (double) |  |  |
| `buyingPower` | number (double) |  |  |
| `cashBalance` | number (double) |  |  |
| `cashAvailableForTrading` | number (double) |  |  |
| `cashReceipts` | number (double) |  |  |
| `dayTradingBuyingPower` | number (double) |  |  |
| `dayTradingBuyingPowerCall` | number (double) |  |  |
| `dayTradingEquityCall` | number (double) |  |  |
| `equity` | number (double) |  |  |
| `equityPercentage` | number (double) |  |  |
| `liquidationValue` | number (double) |  |  |
| `longMarginValue` | number (double) |  |  |
| `longOptionMarketValue` | number (double) |  |  |
| `longStockValue` | number (double) |  |  |
| `maintenanceCall` | number (double) |  |  |
| `maintenanceRequirement` | number (double) |  |  |
| `margin` | number (double) |  |  |
| `marginEquity` | number (double) |  |  |
| `moneyMarketFund` | number (double) |  |  |
| `mutualFundValue` | number (double) |  |  |
| `regTCall` | number (double) |  |  |
| `shortMarginValue` | number (double) |  |  |
| `shortOptionMarketValue` | number (double) |  |  |
| `shortStockValue` | number (double) |  |  |
| `totalCash` | number (double) |  |  |
| `isInCall` | number (double) |  |  |
| `unsettledCash` | number (double) |  |  |
| `pendingDeposits` | number (double) |  |  |
| `marginBalance` | number (double) |  |  |
| `shortBalance` | number (double) |  |  |
| `accountValue` | number (double) |  |  |

---

### Offer

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `level2Permissions` | boolean |  |  |
| `mktDataPermission` | string |  |  |

---

### Order

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `session` | session |  |  |
| `duration` | duration |  |  |
| `orderType` | orderType |  |  |
| `cancelTime` | string (date-time) |  |  |
| `complexOrderStrategyType` | complexOrderStrategyType |  |  |
| `quantity` | number (double) |  |  |
| `filledQuantity` | number (double) |  |  |
| `remainingQuantity` | number (double) |  |  |
| `requestedDestination` | requestedDestination |  |  |
| `destinationLinkName` | string |  |  |
| `releaseTime` | string (date-time) |  |  |
| `stopPrice` | number (double) |  |  |
| `stopPriceLinkBasis` | stopPriceLinkBasis |  |  |
| `stopPriceLinkType` | stopPriceLinkType |  |  |
| `stopPriceOffset` | number (double) |  |  |
| `stopType` | stopType |  |  |
| `priceLinkBasis` | priceLinkBasis |  |  |
| `priceLinkType` | priceLinkType |  |  |
| `price` | number (double) |  |  |
| `taxLotMethod` | taxLotMethod |  |  |
| `orderLegCollection` | array |  |  |
| `activationPrice` | number (double) |  |  |
| `specialInstruction` | specialInstruction |  |  |
| `orderStrategyType` | orderStrategyType |  |  |
| `orderId` | integer (int64) |  |  |
| `cancelable` | boolean |  |  |
| `editable` | boolean |  |  |
| `status` | status |  |  |
| `enteredTime` | string (date-time) |  |  |
| `closeTime` | string (date-time) |  |  |
| `tag` | string |  |  |
| `accountNumber` | integer (int64) |  |  |
| `orderActivityCollection` | array |  |  |
| `replacingOrderCollection` | array |  |  |
| `childOrderStrategies` | array |  |  |
| `statusDescription` | string |  |  |

---

### OrderActivity

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `activityType` | string<br>Values: `EXECUTION`, `ORDER_ACTION` |  |  |
| `executionType` | string<br>Values: `FILL` |  |  |
| `quantity` | number (double) |  |  |
| `orderRemainingQuantity` | number (double) |  |  |
| `executionLegs` | array |  |  |

---

### OrderBalance

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `orderValue` | number (double) |  |  |
| `projectedAvailableFund` | number (double) |  |  |
| `projectedBuyingPower` | number (double) |  |  |
| `projectedCommission` | number (double) |  |  |

---

### OrderLeg

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `askPrice` | number (double) |  |  |
| `bidPrice` | number (double) |  |  |
| `lastPrice` | number (double) |  |  |
| `markPrice` | number (double) |  |  |
| `projectedCommission` | number (double) |  |  |
| `quantity` | number (double) |  |  |
| `finalSymbol` | string |  |  |
| `legId` | number (long) |  |  |
| `assetType` | assetType |  |  |
| `instruction` | instruction |  |  |

---

### OrderLegCollection

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `orderLegType` | string<br>Values: `EQUITY`, `OPTION`, `INDEX`, `MUTUAL_FUND`, `CASH_EQUIVALENT`, `FIXED_INCOME`, `CURRENCY`, `COLLECTIVE_INVESTMENT` |  |  |
| `legId` | integer (int64) |  |  |
| `instrument` | AccountsInstrument |  |  |
| `instruction` | instruction |  |  |
| `positionEffect` | string<br>Values: `OPENING`, `CLOSING`, `AUTOMATIC` |  |  |
| `quantity` | number (double) |  |  |
| `quantityType` | string<br>Values: `ALL_SHARES`, `DOLLARS`, `SHARES` |  |  |
| `divCapGains` | string<br>Values: `REINVEST`, `PAYOUT` |  |  |
| `toSymbol` | string |  |  |

---

### OrderRequest

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `session` | session |  |  |
| `duration` | duration |  |  |
| `orderType` | orderTypeRequest |  |  |
| `cancelTime` | string (date-time) |  |  |
| `complexOrderStrategyType` | complexOrderStrategyType |  |  |
| `quantity` | number (double) |  |  |
| `filledQuantity` | number (double) |  |  |
| `remainingQuantity` | number (double) |  |  |
| `destinationLinkName` | string |  |  |
| `releaseTime` | string (date-time) |  |  |
| `stopPrice` | number (double) |  |  |
| `stopPriceLinkBasis` | stopPriceLinkBasis |  |  |
| `stopPriceLinkType` | stopPriceLinkType |  |  |
| `stopPriceOffset` | number (double) |  |  |
| `stopType` | stopType |  |  |
| `priceLinkBasis` | priceLinkBasis |  |  |
| `priceLinkType` | priceLinkType |  |  |
| `price` | number (double) |  |  |
| `taxLotMethod` | taxLotMethod |  |  |
| `orderLegCollection` | array |  |  |
| `activationPrice` | number (double) |  |  |
| `specialInstruction` | specialInstruction |  |  |
| `orderStrategyType` | orderStrategyType |  |  |
| `orderId` | integer (int64) |  |  |
| `cancelable` | boolean |  |  |
| `editable` | boolean |  |  |
| `status` | status |  |  |
| `enteredTime` | string (date-time) |  |  |
| `closeTime` | string (date-time) |  |  |
| `accountNumber` | integer (int64) |  |  |
| `orderActivityCollection` | array |  |  |
| `replacingOrderCollection` | array |  |  |
| `childOrderStrategies` | array |  |  |
| `statusDescription` | string |  |  |

---

### OrderStrategy

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `accountNumber` | string |  |  |
| `advancedOrderType` | string<br>Values: `NONE`, `OTO`, `OCO`, `OTOCO`, `OT2OCO`, `OT3OCO`, `BLAST_ALL`, `OTA`, `PAIR` |  |  |
| `closeTime` | string (date-time) |  |  |
| `enteredTime` | string (date-time) |  |  |
| `orderBalance` | OrderBalance |  |  |
| `orderStrategyType` | orderStrategyType |  |  |
| `orderVersion` | number |  |  |
| `session` | session |  |  |
| `status` | apiOrderStatus |  |  |
| `allOrNone` | boolean |  |  |
| `discretionary` | boolean |  |  |
| `duration` | duration |  |  |
| `filledQuantity` | number (double) |  |  |
| `orderType` | orderType |  |  |
| `orderValue` | number (double) |  |  |
| `price` | number (double) |  |  |
| `quantity` | number (double) |  |  |
| `remainingQuantity` | number (double) |  |  |
| `sellNonMarginableFirst` | boolean |  |  |
| `settlementInstruction` | settlementInstruction |  |  |
| `strategy` | complexOrderStrategyType |  |  |
| `amountIndicator` | amountIndicator |  |  |
| `orderLegs` | array |  |  |

---

### OrderValidationDetail

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `validationRuleName` | string |  |  |
| `message` | string |  |  |
| `activityMessage` | string |  |  |
| `originalSeverity` | APIRuleAction |  |  |
| `overrideName` | string |  |  |
| `overrideSeverity` | APIRuleAction |  |  |

---

### OrderValidationResult

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `alerts` | array |  |  |
| `accepts` | array |  |  |
| `rejects` | array |  |  |
| `reviews` | array |  |  |
| `warns` | array |  |  |

---

### Position

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `shortQuantity` | number (double) |  |  |
| `averagePrice` | number (double) |  |  |
| `currentDayProfitLoss` | number (double) |  |  |
| `currentDayProfitLossPercentage` | number (double) |  |  |
| `longQuantity` | number (double) |  |  |
| `settledLongQuantity` | number (double) |  |  |
| `settledShortQuantity` | number (double) |  |  |
| `agedQuantity` | number (double) |  |  |
| `instrument` | AccountsInstrument |  |  |
| `marketValue` | number (double) |  |  |
| `maintenanceRequirement` | number (double) |  |  |
| `averageLongPrice` | number (double) |  |  |
| `averageShortPrice` | number (double) |  |  |
| `taxLotAverageLongPrice` | number (double) |  |  |
| `taxLotAverageShortPrice` | number (double) |  |  |
| `longOpenProfitLoss` | number (double) |  |  |
| `shortOpenProfitLoss` | number (double) |  |  |
| `previousSessionLongQuantity` | number (double) |  |  |
| `previousSessionShortQuantity` | number (double) |  |  |
| `currentDayCost` | number (double) |  |  |

---

### PreviewOrder

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `orderId` | integer (int64) |  |  |
| `orderStrategy` | OrderStrategy |  |  |
| `orderValidationResult` | OrderValidationResult |  |  |
| `commissionAndFee` | CommissionAndFee |  |  |

---

### Product

**Composed of:**

- TransactionBaseInstrument

---

### SecuritiesAccount

**One of the following types:**

1. MarginAccount
2. CashAccount

---

### SecuritiesAccountBase

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `type` | string<br>Values: `CASH`, `MARGIN` |  |  |
| `accountNumber` | string |  |  |
| `roundTrips` | integer (int32) |  |  |
| `isDayTrader` | boolean |  |  |
| `isClosingOnlyRestricted` | boolean |  |  |
| `pfcbFlag` | boolean |  |  |
| `positions` | array |  |  |

---

### ServiceError

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `message` | string |  |  |
| `errors` | array |  |  |

---

### StreamerInfo

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `streamerSocketUrl` | string |  |  |
| `schwabClientCustomerId` | string |  |  |
| `schwabClientCorrelId` | string |  |  |
| `schwabClientChannel` | string |  |  |
| `schwabClientFunctionId` | string |  |  |

---

### Transaction

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `activityId` | integer (int64) |  |  |
| `time` | string (date-time) |  |  |
| `user` | UserDetails |  |  |
| `description` | string |  |  |
| `accountNumber` | string |  |  |
| `type` | TransactionType |  |  |
| `status` | string<br>Values: `VALID`, `INVALID`, `PENDING`, `UNKNOWN` |  |  |
| `subAccount` | string<br>Values: `CASH`, `MARGIN`, `SHORT`, `DIV`, `INCOME`, `UNKNOWN` |  |  |
| `tradeDate` | string (date-time) |  |  |
| `settlementDate` | string (date-time) |  |  |
| `positionId` | integer (int64) |  |  |
| `orderId` | integer (int64) |  |  |
| `netAmount` | number (double) |  |  |
| `activityType` | string<br>Values: `ACTIVITY_CORRECTION`, `EXECUTION`, `ORDER_ACTION`, `TRANSFER`, `UNKNOWN` |  |  |
| `transferItems` | array |  |  |

---

### TransactionAPIOptionDeliverable

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `rootSymbol` | string |  |  |
| `strikePercent` | integer (int64) |  |  |
| `deliverableNumber` | integer (int64) |  |  |
| `deliverableUnits` | number (double) |  |  |
| `deliverable` | TransactionInstrument |  |  |
| `assetType` | assetType |  |  |

---

### TransactionBaseInstrument

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `assetType` | string<br>Values: `EQUITY`, `OPTION`, `INDEX`, `MUTUAL_FUND`, `CASH_EQUIVALENT`, `FIXED_INCOME`, `CURRENCY`, `COLLECTIVE_INVESTMENT` | ✓ |  |
| `cusip` | string |  |  |
| `symbol` | string |  |  |
| `description` | string |  |  |
| `instrumentId` | integer (int64) |  |  |
| `netChange` | number (double) |  |  |

---

### TransactionCashEquivalent

**Composed of:**

- TransactionBaseInstrument

---

### TransactionEquity

**Composed of:**

- TransactionBaseInstrument

---

### TransactionFixedIncome

**Composed of:**

- TransactionBaseInstrument

---

### TransactionInstrument

**One of the following types:**

1. TransactionCashEquivalent
2. CollectiveInvestment
3. Currency
4. TransactionEquity
5. TransactionFixedIncome
6. Forex
7. Future
8. Index
9. TransactionMutualFund
10. TransactionOption
11. Product

---

### TransactionMutualFund

**Composed of:**

- TransactionBaseInstrument

---

### TransactionOption

**Composed of:**

- TransactionBaseInstrument

---

### TransactionType

**Type:** Enum (string)


**Allowed Values:**
- `TRADE`
- `RECEIVE_AND_DELIVER`
- `DIVIDEND_OR_INTEREST`
- `ACH_RECEIPT`
- `ACH_DISBURSEMENT`
- `CASH_RECEIPT`
- `CASH_DISBURSEMENT`
- `ELECTRONIC_FUND`
- `WIRE_OUT`
- `WIRE_IN`
- `JOURNAL`
- `MEMORANDUM`
- `MARGIN_CALL`
- `MONEY_MARKET`
- `SMA_ADJUSTMENT`

---

### TransferItem

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `instrument` | TransactionInstrument |  |  |
| `amount` | number (double) |  |  |
| `cost` | number (double) |  |  |
| `price` | number (double) |  |  |
| `feeType` | string<br>Values: `COMMISSION`, `SEC_FEE`, `STR_FEE`, `R_FEE`, `CDSC_FEE`, `OPT_REG_FEE`, `ADDITIONAL_FEE`, `MISCELLANEOUS_FEE`, `FUTURES_EXCHANGE_FEE`, `LOW_PROCEEDS_COMMISSION`... |  |  |
| `positionEffect` | string<br>Values: `OPENING`, `CLOSING`, `AUTOMATIC`, `UNKNOWN` |  |  |

---

### UserDetails

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `cdDomainId` | string |  |  |
| `login` | string |  |  |
| `type` | string<br>Values: `ADVISOR_USER`, `BROKER_USER`, `CLIENT_USER`, `SYSTEM_USER`, `UNKNOWN` |  |  |
| `userId` | integer (int64) |  |  |
| `systemUserName` | string |  |  |
| `firstName` | string |  |  |
| `lastName` | string |  |  |
| `brokerRepCode` | string |  |  |

---

### UserPreference

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `accounts` | array |  |  |
| `streamerInfo` | array |  |  |
| `offers` | array |  |  |

---

### UserPreferenceAccount

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `accountNumber` | string |  |  |
| `primaryAccount` | boolean |  |  |
| `type` | string |  |  |
| `nickName` | string |  |  |
| `accountColor` | string |  | Green | Blue |
| `displayAcctId` | string |  |  |
| `autoPositionEffect` | boolean |  |  |

---

### amountIndicator

**Type:** Enum (string)


**Allowed Values:**
- `DOLLARS`
- `SHARES`
- `ALL_SHARES`
- `PERCENTAGE`
- `UNKNOWN`

---

### apiOrderStatus

**Type:** Enum (string)


**Allowed Values:**
- `AWAITING_PARENT_ORDER`
- `AWAITING_CONDITION`
- `AWAITING_STOP_CONDITION`
- `AWAITING_MANUAL_REVIEW`
- `ACCEPTED`
- `AWAITING_UR_OUT`
- `PENDING_ACTIVATION`
- `QUEUED`
- `WORKING`
- `REJECTED`
- `PENDING_CANCEL`
- `CANCELED`
- `PENDING_REPLACE`
- `REPLACED`
- `FILLED`
- `EXPIRED`
- `NEW`
- `AWAITING_RELEASE_TIME`
- `PENDING_ACKNOWLEDGEMENT`
- `PENDING_RECALL`
- `UNKNOWN`

---

### assetType

**Type:** Enum (string)


**Allowed Values:**
- `EQUITY`
- `MUTUAL_FUND`
- `OPTION`
- `FUTURE`
- `FOREX`
- `INDEX`
- `CASH_EQUIVALENT`
- `FIXED_INCOME`
- `PRODUCT`
- `CURRENCY`
- `COLLECTIVE_INVESTMENT`

---

### complexOrderStrategyType

**Type:** Enum (string)


**Allowed Values:**
- `NONE`
- `COVERED`
- `VERTICAL`
- `BACK_RATIO`
- `CALENDAR`
- `DIAGONAL`
- `STRADDLE`
- `STRANGLE`
- `COLLAR_SYNTHETIC`
- `BUTTERFLY`
- `CONDOR`
- `IRON_CONDOR`
- `VERTICAL_ROLL`
- `COLLAR_WITH_STOCK`
- `DOUBLE_DIAGONAL`
- `UNBALANCED_BUTTERFLY`
- `UNBALANCED_CONDOR`
- `UNBALANCED_IRON_CONDOR`
- `UNBALANCED_VERTICAL_ROLL`
- `MUTUAL_FUND_SWAP`
- `CUSTOM`

---

### duration

**Type:** Enum (string)


**Allowed Values:**
- `DAY`
- `GOOD_TILL_CANCEL`
- `FILL_OR_KILL`
- `IMMEDIATE_OR_CANCEL`
- `END_OF_WEEK`
- `END_OF_MONTH`
- `NEXT_END_OF_MONTH`
- `UNKNOWN`

---

### instruction

**Type:** Enum (string)


**Allowed Values:**
- `BUY`
- `SELL`
- `BUY_TO_COVER`
- `SELL_SHORT`
- `BUY_TO_OPEN`
- `BUY_TO_CLOSE`
- `SELL_TO_OPEN`
- `SELL_TO_CLOSE`
- `EXCHANGE`
- `SELL_SHORT_EXEMPT`

---

### orderStrategyType

**Type:** Enum (string)


**Allowed Values:**
- `SINGLE`
- `CANCEL`
- `RECALL`
- `PAIR`
- `FLATTEN`
- `TWO_DAY_SWAP`
- `BLAST_ALL`
- `OCO`
- `TRIGGER`

---

### orderType

**Type:** Enum (string)


**Allowed Values:**
- `MARKET`
- `LIMIT`
- `STOP`
- `STOP_LIMIT`
- `TRAILING_STOP`
- `CABINET`
- `NON_MARKETABLE`
- `MARKET_ON_CLOSE`
- `EXERCISE`
- `TRAILING_STOP_LIMIT`
- `NET_DEBIT`
- `NET_CREDIT`
- `NET_ZERO`
- `LIMIT_ON_CLOSE`
- `UNKNOWN`

---

### orderTypeRequest

Same as orderType, but does not have UNKNOWN since this type is not allowed as an input


**Type:** Enum (string)


**Allowed Values:**
- `MARKET`
- `LIMIT`
- `STOP`
- `STOP_LIMIT`
- `TRAILING_STOP`
- `CABINET`
- `NON_MARKETABLE`
- `MARKET_ON_CLOSE`
- `EXERCISE`
- `TRAILING_STOP_LIMIT`
- `NET_DEBIT`
- `NET_CREDIT`
- `NET_ZERO`
- `LIMIT_ON_CLOSE`

---

### priceLinkBasis

**Type:** Enum (string)


**Allowed Values:**
- `MANUAL`
- `BASE`
- `TRIGGER`
- `LAST`
- `BID`
- `ASK`
- `ASK_BID`
- `MARK`
- `AVERAGE`

---

### priceLinkType

**Type:** Enum (string)


**Allowed Values:**
- `VALUE`
- `PERCENT`
- `TICK`

---

### requestedDestination

**Type:** Enum (string)


**Allowed Values:**
- `INET`
- `ECN_ARCA`
- `CBOE`
- `AMEX`
- `PHLX`
- `ISE`
- `BOX`
- `NYSE`
- `NASDAQ`
- `BATS`
- `C2`
- `AUTO`

---

### session

**Type:** Enum (string)


**Allowed Values:**
- `NORMAL`
- `AM`
- `PM`
- `SEAMLESS`

---

### settlementInstruction

**Type:** Enum (string)


**Allowed Values:**
- `REGULAR`
- `CASH`
- `NEXT_DAY`
- `UNKNOWN`

---

### specialInstruction

**Type:** Enum (string)


**Allowed Values:**
- `ALL_OR_NONE`
- `DO_NOT_REDUCE`
- `ALL_OR_NONE_DO_NOT_REDUCE`

---

### status

**Type:** Enum (string)


**Allowed Values:**
- `AWAITING_PARENT_ORDER`
- `AWAITING_CONDITION`
- `AWAITING_STOP_CONDITION`
- `AWAITING_MANUAL_REVIEW`
- `ACCEPTED`
- `AWAITING_UR_OUT`
- `PENDING_ACTIVATION`
- `QUEUED`
- `WORKING`
- `REJECTED`
- `PENDING_CANCEL`
- `CANCELED`
- `PENDING_REPLACE`
- `REPLACED`
- `FILLED`
- `EXPIRED`
- `NEW`
- `AWAITING_RELEASE_TIME`
- `PENDING_ACKNOWLEDGEMENT`
- `PENDING_RECALL`
- `UNKNOWN`

---

### stopPriceLinkBasis

**Type:** Enum (string)


**Allowed Values:**
- `MANUAL`
- `BASE`
- `TRIGGER`
- `LAST`
- `BID`
- `ASK`
- `ASK_BID`
- `MARK`
- `AVERAGE`

---

### stopPriceLinkType

**Type:** Enum (string)


**Allowed Values:**
- `VALUE`
- `PERCENT`
- `TICK`

---

### stopPriceOffset

---

### stopType

**Type:** Enum (string)


**Allowed Values:**
- `STANDARD`
- `BID`
- `ASK`
- `LAST`
- `MARK`

---

### taxLotMethod

**Type:** Enum (string)


**Allowed Values:**
- `FIFO`
- `LIFO`
- `HIGH_COST`
- `LOW_COST`
- `AVERAGE_COST`
- `SPECIFIC_LOT`
- `LOSS_HARVESTER`

---
