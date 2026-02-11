# Schwab API Quick Reference

Quick reference guide with common code examples for the Schwab Trader API.

## Table of Contents

- [Authentication](#authentication)
- [Market Data Examples](#market-data-examples)
- [Account Management](#account-management)
- [Order Management](#order-management)
- [Transaction Queries](#transaction-queries)
- [Error Handling](#error-handling)

## Authentication

### Initial Authorization (Python)

```python
import requests
import base64
from urllib.parse import urlencode

# Your credentials (use environment variables in production!)
CLIENT_ID = 'YOUR_APP_KEY'
CLIENT_SECRET = 'YOUR_APP_SECRET'
REDIRECT_URI = 'https://your-app.com/callback'

# Step 1: Build authorization URL
auth_params = {
    'client_id': CLIENT_ID,
    'redirect_uri': REDIRECT_URI,
    'response_type': 'code',
    'state': 'RANDOM_SECURE_STRING'  # Generate unique per request
}

auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?{urlencode(auth_params)}"
print(f"Visit this URL to authorize: {auth_url}")

# Step 2: After user authorizes, extract code from callback
# Example callback: https://your-app.com/callback?code=AUTH_CODE&state=RANDOM_SECURE_STRING

# Step 3: Exchange code for tokens
def get_tokens(auth_code):
    token_url = 'https://api.schwabapi.com/v1/oauth/token'
    
    # Encode credentials
    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    b64_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        'Authorization': f'Basic {b64_credentials}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    data = {
        'grant_type': 'authorization_code',
        'code': auth_code,
        'redirect_uri': REDIRECT_URI
    }
    
    response = requests.post(token_url, headers=headers, data=data)
    return response.json()

# tokens = get_tokens('YOUR_AUTH_CODE')
# access_token = tokens['access_token']
# refresh_token = tokens['refresh_token']
```

### Token Refresh (Python)

```python
def refresh_access_token(refresh_token):
    token_url = 'https://api.schwabapi.com/v1/oauth/token'
    
    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    b64_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        'Authorization': f'Basic {b64_credentials}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }
    
    response = requests.post(token_url, headers=headers, data=data)
    return response.json()
```

### Token Management Class (Python)

```python
import time
from datetime import datetime, timedelta

class TokenManager:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
    
    def set_tokens(self, token_response):
        self.access_token = token_response['access_token']
        self.refresh_token = token_response['refresh_token']
        expires_in = token_response['expires_in']
        self.token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)  # 60s buffer
    
    def is_token_valid(self):
        return self.access_token and datetime.now() < self.token_expiry
    
    def get_valid_token(self):
        if not self.is_token_valid():
            new_tokens = refresh_access_token(self.refresh_token)
            self.set_tokens(new_tokens)
        return self.access_token
    
    def get_auth_header(self):
        return {'Authorization': f'Bearer {self.get_valid_token()}'}
```

## Market Data Examples

### Get Single Stock Quote (Python)

```python
def get_quote(symbol, access_token):
    url = f'https://api.schwabapi.com/marketdata/v1/{symbol}/quotes'
    headers = {'Authorization': f'Bearer {access_token}'}
    
    response = requests.get(url, headers=headers)
    return response.json()

# Example
quote = get_quote('AAPL', access_token)
print(f"Price: ${quote['quote']['lastPrice']}")
print(f"Bid: ${quote['quote']['bidPrice']} x {quote['quote']['bidSize']}")
print(f"Ask: ${quote['quote']['askPrice']} x {quote['quote']['askSize']}")
```

### Get Multiple Quotes (Python)

```python
def get_multiple_quotes(symbols, access_token):
    url = 'https://api.schwabapi.com/marketdata/v1/quotes'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'symbols': ','.join(symbols)}
    
    response = requests.get(url, headers=headers, params=params)
    return response.json()

# Example
symbols = ['AAPL', 'MSFT', 'GOOGL', 'TSLA']
quotes = get_multiple_quotes(symbols, access_token)

for symbol, data in quotes.items():
    print(f"{symbol}: ${data['quote']['lastPrice']}")
```

### Get Option Chain (Python)

```python
def get_option_chain(symbol, access_token, contract_type='ALL', strike_count=10):
    url = 'https://api.schwabapi.com/marketdata/v1/chains'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {
        'symbol': symbol,
        'contractType': contract_type,  # ALL, CALL, PUT
        'strikeCount': strike_count,
        'includeQuotes': 'TRUE'
    }
    
    response = requests.get(url, headers=headers, params=params)
    return response.json()

# Example - Get calls near the money
options = get_option_chain('AAPL', access_token, contract_type='CALL', strike_count=5)
```

### Get Price History/Chart Data (Python)

```python
def get_price_history(symbol, access_token, period_type='day', period=10, frequency=1):
    url = f'https://api.schwabapi.com/marketdata/v1/{symbol}/pricehistory'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {
        'periodType': period_type,  # day, month, year, ytd
        'period': period,
        'frequencyType': 'minute' if period_type == 'day' else 'daily',
        'frequency': frequency
    }
    
    response = requests.get(url, headers=headers, params=params)
    return response.json()

# Example - Get 10 days of daily data
history = get_price_history('AAPL', access_token, period_type='month', period=1)

for candle in history['candles'][:5]:
    print(f"Date: {candle['datetime']}, Close: ${candle['close']}")
```

### Get Market Hours (Python)

```python
def get_market_hours(markets, access_token, date=None):
    url = 'https://api.schwabapi.com/marketdata/v1/markets'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {
        'markets': ','.join(markets)  # equity, option, bond, future, forex
    }
    if date:
        params['date'] = date  # YYYY-MM-DD
    
    response = requests.get(url, headers=headers, params=params)
    return response.json()

# Example
hours = get_market_hours(['equity', 'option'], access_token)
```

## Account Management

### Get All Account Numbers (Python)

```python
def get_account_numbers(access_token):
    url = 'https://api.schwabapi.com/trader/v1/accounts/accountNumbers'
    headers = {'Authorization': f'Bearer {access_token}'}
    
    response = requests.get(url, headers=headers)
    return response.json()

# Example
accounts = get_account_numbers(access_token)
for account in accounts:
    print(f"Account: {account['accountNumber']} ({account['hashValue']})")
```

### Get All Account Balances (Python)

```python
def get_all_accounts(access_token, include_positions=True):
    url = 'https://api.schwabapi.com/trader/v1/accounts'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {
        'fields': 'positions' if include_positions else None
    }
    
    response = requests.get(url, headers=headers, params=params)
    return response.json()

# Example
accounts = get_all_accounts(access_token)
for account in accounts:
    balance = account['securitiesAccount']['currentBalances']
    print(f"Account: {account['securitiesAccount']['accountNumber']}")
    print(f"  Cash: ${balance['cashBalance']:.2f}")
    print(f"  Total Value: ${balance['liquidationValue']:.2f}")
```

### Get Specific Account Details (Python)

```python
def get_account_details(account_number, access_token, include_positions=True):
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {
        'fields': 'positions' if include_positions else None
    }
    
    response = requests.get(url, headers=headers, params=params)
    return response.json()

# Example
account = get_account_details('123456789', access_token)

# Print positions
if 'positions' in account['securitiesAccount']:
    print("\nPositions:")
    for position in account['securitiesAccount']['positions']:
        instrument = position['instrument']
        print(f"  {instrument['symbol']}: {position['longQuantity']} shares @ ${position['averagePrice']:.2f}")
```

## Order Management

### Place Market Order (Python)

```python
def place_market_order(account_number, symbol, quantity, instruction, access_token):
    """
    instruction: 'BUY', 'SELL', 'BUY_TO_COVER', 'SELL_SHORT'
    """
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}/orders'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    order = {
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": instruction,
                "quantity": quantity,
                "instrument": {
                    "symbol": symbol,
                    "assetType": "EQUITY"
                }
            }
        ]
    }
    
    response = requests.post(url, headers=headers, json=order)
    return response

# Example
response = place_market_order('123456789', 'AAPL', 10, 'BUY', access_token)
if response.status_code == 201:
    order_id = response.headers.get('location').split('/')[-1]
    print(f"Order placed successfully. Order ID: {order_id}")
```

### Place Limit Order (Python)

```python
def place_limit_order(account_number, symbol, quantity, price, instruction, access_token):
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}/orders'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    order = {
        "orderType": "LIMIT",
        "session": "NORMAL",
        "duration": "DAY",
        "price": str(price),
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": instruction,
                "quantity": quantity,
                "instrument": {
                    "symbol": symbol,
                    "assetType": "EQUITY"
                }
            }
        ]
    }
    
    response = requests.post(url, headers=headers, json=order)
    return response

# Example
response = place_limit_order('123456789', 'AAPL', 10, 150.00, 'BUY', access_token)
```

### Place Stop Loss Order (Python)

```python
def place_stop_order(account_number, symbol, quantity, stop_price, instruction, access_token):
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}/orders'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    order = {
        "orderType": "STOP",
        "session": "NORMAL",
        "duration": "DAY",
        "stopPrice": str(stop_price),
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": instruction,
                "quantity": quantity,
                "instrument": {
                    "symbol": symbol,
                    "assetType": "EQUITY"
                }
            }
        ]
    }
    
    response = requests.post(url, headers=headers, json=order)
    return response

# Example - Stop loss at $145
response = place_stop_order('123456789', 'AAPL', 10, 145.00, 'SELL', access_token)
```

### Place Option Order (Python)

```python
def place_option_order(account_number, symbol, quantity, instruction, access_token):
    """
    instruction: 'BUY_TO_OPEN', 'SELL_TO_CLOSE', 'BUY_TO_CLOSE', 'SELL_TO_OPEN'
    symbol: Full option symbol (e.g., 'AAPL_011524C150')
    """
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}/orders'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    order = {
        "orderType": "LIMIT",
        "session": "NORMAL",
        "duration": "DAY",
        "price": "5.00",  # Set your limit price
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": instruction,
                "quantity": quantity,
                "instrument": {
                    "symbol": symbol,
                    "assetType": "OPTION"
                }
            }
        ]
    }
    
    response = requests.post(url, headers=headers, json=order)
    return response
```

### Get Account Orders (Python)

```python
def get_orders(account_number, access_token, from_date=None, to_date=None, status=None):
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}/orders'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {}
    
    if from_date:
        params['fromEnteredTime'] = from_date  # ISO-8601 format
    if to_date:
        params['toEnteredTime'] = to_date
    if status:
        params['status'] = status  # AWAITING_PARENT_ORDER, AWAITING_CONDITION, etc.
    
    response = requests.get(url, headers=headers, params=params)
    return response.json()

# Example - Get today's orders
from datetime import datetime
today = datetime.now().strftime('%Y-%m-%d')
orders = get_orders('123456789', access_token, from_date=today)

for order in orders:
    print(f"Order {order['orderId']}: {order['status']}")
```

### Get Specific Order (Python)

```python
def get_order(account_number, order_id, access_token):
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}/orders/{order_id}'
    headers = {'Authorization': f'Bearer {access_token}'}
    
    response = requests.get(url, headers=headers)
    return response.json()
```

### Cancel Order (Python)

```python
def cancel_order(account_number, order_id, access_token):
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}/orders/{order_id}'
    headers = {'Authorization': f'Bearer {access_token}'}
    
    response = requests.delete(url, headers=headers)
    return response.status_code == 200

# Example
if cancel_order('123456789', '98765', access_token):
    print("Order cancelled successfully")
```

### Preview Order (Python)

```python
def preview_order(account_number, order_spec, access_token):
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}/previewOrder'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    response = requests.post(url, headers=headers, json=order_spec)
    return response.json()

# Example
order_spec = {
    "orderType": "LIMIT",
    "session": "NORMAL",
    "duration": "DAY",
    "price": "150.00",
    "orderStrategyType": "SINGLE",
    "orderLegCollection": [
        {
            "instruction": "BUY",
            "quantity": 10,
            "instrument": {
                "symbol": "AAPL",
                "assetType": "EQUITY"
            }
        }
    ]
}

preview = preview_order('123456789', order_spec, access_token)
print(f"Estimated cost: ${preview['orderActivity'][0]['executionLegs'][0]['price']}")
```

## Transaction Queries

### Get Transactions (Python)

```python
def get_transactions(account_number, access_token, start_date, end_date, types=None):
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}/transactions'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {
        'startDate': start_date,  # YYYY-MM-DD
        'endDate': end_date
    }
    
    if types:
        params['types'] = ','.join(types)  # TRADE, RECEIVE_AND_DELIVER, DIVIDEND, etc.
    
    response = requests.get(url, headers=headers, params=params)
    return response.json()

# Example - Get all trades for 2024
transactions = get_transactions(
    '123456789',
    access_token,
    '2024-01-01',
    '2024-12-31',
    types=['TRADE']
)

for txn in transactions:
    print(f"{txn['transactionDate']}: {txn['description']}")
```

### Get Specific Transaction (Python)

```python
def get_transaction(account_number, transaction_id, access_token):
    url = f'https://api.schwabapi.com/trader/v1/accounts/{account_number}/transactions/{transaction_id}'
    headers = {'Authorization': f'Bearer {access_token}'}
    
    response = requests.get(url, headers=headers)
    return response.json()
```

## Error Handling

### Comprehensive Error Handler (Python)

```python
class SchwabAPIError(Exception):
    pass

def make_api_request(method, url, access_token, **kwargs):
    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {access_token}'
    
    response = requests.request(method, url, headers=headers, **kwargs)
    
    if response.status_code == 200 or response.status_code == 201:
        return response
    elif response.status_code == 400:
        raise SchwabAPIError(f"Bad Request: {response.text}")
    elif response.status_code == 401:
        raise SchwabAPIError("Unauthorized: Token may be expired")
    elif response.status_code == 404:
        raise SchwabAPIError(f"Not Found: {url}")
    elif response.status_code == 500:
        raise SchwabAPIError("Server Error: Try again later")
    else:
        raise SchwabAPIError(f"Unknown Error ({response.status_code}): {response.text}")

# Usage
try:
    response = make_api_request(
        'GET',
        'https://api.schwabapi.com/trader/v1/accounts',
        access_token
    )
    accounts = response.json()
except SchwabAPIError as e:
    print(f"API Error: {e}")
```

### Retry Logic with Exponential Backoff (Python)

```python
import time

def api_request_with_retry(func, max_retries=3, backoff_factor=2):
    for attempt in range(max_retries):
        try:
            return func()
        except SchwabAPIError as e:
            if attempt == max_retries - 1:
                raise
            
            wait_time = backoff_factor ** attempt
            print(f"Request failed. Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
    
# Usage
result = api_request_with_retry(lambda: get_quote('AAPL', access_token))
```

## Complete Example: Trading Bot

```python
class SchwabTradingBot:
    def __init__(self, client_id, client_secret, account_number):
        self.token_manager = TokenManager(client_id, client_secret)
        self.account_number = account_number
    
    def get_current_price(self, symbol):
        quote = get_quote(symbol, self.token_manager.get_valid_token())
        return quote['quote']['lastPrice']
    
    def get_position_quantity(self, symbol):
        account = get_account_details(
            self.account_number,
            self.token_manager.get_valid_token()
        )
        
        positions = account['securitiesAccount'].get('positions', [])
        for position in positions:
            if position['instrument']['symbol'] == symbol:
                return position['longQuantity']
        return 0
    
    def simple_momentum_strategy(self, symbol):
        # Get price history
        history = get_price_history(
            symbol,
            self.token_manager.get_valid_token(),
            period_type='day',
            period=10
        )
        
        candles = history['candles']
        closes = [c['close'] for c in candles]
        
        # Simple momentum: buy if trending up
        if len(closes) >= 5:
            recent_avg = sum(closes[-5:]) / 5
            older_avg = sum(closes[-10:-5]) / 5
            
            current_position = self.get_position_quantity(symbol)
            
            if recent_avg > older_avg and current_position == 0:
                print(f"BUY signal for {symbol}")
                place_market_order(
                    self.account_number,
                    symbol,
                    10,
                    'BUY',
                    self.token_manager.get_valid_token()
                )
            elif recent_avg < older_avg and current_position > 0:
                print(f"SELL signal for {symbol}")
                place_market_order(
                    self.account_number,
                    symbol,
                    current_position,
                    'SELL',
                    self.token_manager.get_valid_token()
                )

# Usage
# bot = SchwabTradingBot(CLIENT_ID, CLIENT_SECRET, '123456789')
# bot.simple_momentum_strategy('AAPL')
```

---

## Additional Resources

- See [README.md](README.md) for complete API overview
- See [OAuth_Authentication_Guide.md](OAuth_Authentication_Guide.md) for authentication details
- See [Market_Data_API.md](Market_Data_API.md) for complete Market Data documentation
- See [Retail_Trader_API.md](Retail_Trader_API.md) for complete Trader API documentation
