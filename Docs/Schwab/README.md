# Schwab Trader API Documentation

Comprehensive Markdown documentation for the Charles Schwab Trader API, converted from OpenAPI specifications for easy reference and version control.

## Overview

This repository contains complete documentation for two Schwab API products:

1. **Market Data API** - Real-time and historical market data, quotes, option chains, and market hours
2. **Retail Trader API** - Account access, order management, transaction history, and user preferences

All documentation has been converted from official OpenAPI specifications to Markdown format, preserving all technical details including endpoints, parameters, request/response schemas, and data types.

## Documentation Files

### API References

- **[Market_Data_API.md](Market_Data_API.md)** - Complete Market Data API documentation
  - Quotes (real-time and delayed)
  - Option Chains and Expiration Chains
  - Price History
  - Market Movers
  - Market Hours
  - Instrument Search

- **[Retail_Trader_API.md](Retail_Trader_API.md)** - Complete Trader API documentation
  - Account Information and Numbers
  - Order Management (GET, POST, PUT, DELETE)
  - Order Preview
  - Transaction History
  - User Preferences

### Authentication

- **[OAuth_Authentication_Guide.md](OAuth_Authentication_Guide.md)** - Comprehensive OAuth 2.0 implementation guide
  - Three-Legged OAuth Flow
  - Token Management
  - Security Best Practices
  - Error Handling
  - Code Examples

## Quick Start

### Prerequisites

1. Register for a Schwab Developer account at https://developer.schwab.com
2. Create an application to obtain:
   - **App Key (Client ID)**
   - **App Secret (Client Secret)**
   - **Redirect URI**

> ⚠️ **Security Warning:** Never commit your Client Secret to version control. Use environment variables or secure configuration management.

### Authentication Flow

1. **Authorize your application:**
   ```
   https://api.schwabapi.com/v1/oauth/authorize?
     client_id=YOUR_APP_KEY&
     redirect_uri=YOUR_REDIRECT_URI&
     response_type=code&
     state=RANDOM_STRING
   ```

2. **Exchange authorization code for tokens:**
   ```bash
   curl -X POST https://api.schwabapi.com/v1/oauth/token \
     -H "Authorization: Basic BASE64(client_id:client_secret)" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=authorization_code" \
     -d "code=AUTH_CODE" \
     -d "redirect_uri=YOUR_REDIRECT_URI"
   ```

3. **Make API requests:**
   ```bash
   curl -X GET https://api.schwabapi.com/trader/v1/accounts \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
   ```

See [OAuth_Authentication_Guide.md](OAuth_Authentication_Guide.md) for complete details.

## API Endpoints Overview

### Market Data API

**Base URL:** `https://api.schwabapi.com/marketdata/v1`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/quotes` | GET | Get quotes for multiple symbols |
| `/{symbol_id}/quotes` | GET | Get quote for a single symbol |
| `/chains` | GET | Get option chains |
| `/expirationchain` | GET | Get option expiration chain |
| `/pricehistory` | GET | Get price history/charts |
| `/movers/{symbol_id}` | GET | Get market movers |
| `/markets` | GET | Get market hours for all markets |
| `/markets/{market_id}` | GET | Get market hours for specific market |
| `/instruments` | GET | Search instruments |
| `/instruments/{cusip_id}` | GET | Get instrument by CUSIP |

### Retail Trader API

**Base URL:** `https://api.schwabapi.com/trader/v1`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/accounts/accountNumbers` | GET | Get list of account numbers |
| `/accounts` | GET | Get all linked account balances |
| `/accounts/{accountNumber}` | GET | Get specific account details |
| `/accounts/{accountNumber}/orders` | GET | Get orders for an account |
| `/accounts/{accountNumber}/orders` | POST | Place an order |
| `/accounts/{accountNumber}/orders/{orderId}` | GET | Get specific order |
| `/accounts/{accountNumber}/orders/{orderId}` | DELETE | Cancel an order |
| `/accounts/{accountNumber}/orders/{orderId}` | PUT | Replace an order |
| `/orders` | GET | Get orders for all accounts |
| `/accounts/{accountNumber}/previewOrder` | POST | Preview an order |
| `/accounts/{accountNumber}/transactions` | GET | Get account transactions |
| `/accounts/{accountNumber}/transactions/{transactionId}` | GET | Get specific transaction |
| `/userPreference` | GET | Get user preferences |

## Common Use Cases

### Get Real-Time Quote

```bash
GET /marketdata/v1/AAPL/quotes
Authorization: Bearer {access_token}
```

### Get Account Balances

```bash
GET /trader/v1/accounts
Authorization: Bearer {access_token}
```

### Place a Market Order

```bash
POST /trader/v1/accounts/{accountNumber}/orders
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "orderType": "MARKET",
  "session": "NORMAL",
  "duration": "DAY",
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
```

### Get Transaction History

```bash
GET /trader/v1/accounts/{accountNumber}/transactions?types=TRADE&startDate=2024-01-01&endDate=2024-12-31
Authorization: Bearer {access_token}
```

## Data Schemas

Both APIs include comprehensive schema definitions for all data types:

### Market Data Schemas (57 total)
- Quote types (Equity, Option, Forex, Future, Index, Mutual Fund)
- Option Chain data structures
- Price History (Candle data)
- Market Mover information
- Market Hours schedules
- Instrument details

### Trader API Schemas (84 total)
- Account types (Cash, Margin)
- Order types (Market, Limit, Stop, Stop Limit, Trailing Stop)
- Order strategies (Single, OCO, Trigger)
- Position information
- Transaction details
- User preferences

See the individual API documentation files for complete schema definitions.

## Error Handling

All endpoints return standard HTTP status codes:

| Code | Meaning | Description |
|------|---------|-------------|
| 200 | OK | Successful request |
| 201 | Created | Order successfully placed |
| 400 | Bad Request | Invalid parameters or malformed request |
| 401 | Unauthorized | Invalid or expired access token |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource not found |
| 500 | Internal Server Error | Server-side error |

Error responses include detailed messages to help diagnose issues.

## Rate Limiting

The Schwab API implements rate limiting to ensure fair usage:

- Monitor response headers for rate limit information
- Implement exponential backoff for retries
- Cache responses when appropriate
- Avoid excessive polling

## Security Best Practices

### Credential Management

✅ **DO:**
- Store credentials in environment variables
- Use secure configuration management (e.g., AWS Secrets Manager, Azure Key Vault)
- Rotate secrets regularly
- Use HTTPS for all requests
- Implement proper session management

❌ **DON'T:**
- Commit credentials to version control
- Expose secrets in client-side code
- Log access tokens or refresh tokens
- Share credentials across environments
- Use HTTP for OAuth or API requests

### Token Management

- Access tokens expire after 30 minutes - implement refresh logic
- Refresh tokens are valid for 7 days - store securely
- Check token expiration before making requests
- Handle token refresh failures gracefully

## Support and Resources

### Official Resources
- [Schwab Developer Portal](https://developer.schwab.com)
- [API Documentation](https://developer.schwab.com/products)
- Developer Support: Contact through Developer Portal

### Technical Specifications
- OpenAPI Version: 3.0.1 (Trader API) / 3.0.3 (Market Data API)
- API Version: 1.0.0 (both APIs)
- Authentication: OAuth 2.0 Authorization Code Flow

## Version History

### Current Version
- API Version: 1.0.0
- Documentation Generated: February 2026
- Source: Official Schwab OpenAPI Specifications

## Contributing

This documentation is maintained as a reference. For API changes or issues:

1. Contact Schwab Developer Support
2. Check the official Developer Portal for updates
3. Review OpenAPI specifications for the latest changes

## License

This documentation is provided for reference purposes. API usage is subject to Schwab's Terms of Service and API Agreement.

## Disclaimer

This documentation is an unofficial conversion of Schwab's OpenAPI specifications to Markdown format. Always refer to the official Schwab Developer Portal for the most current information and legal terms.

**Important:** Trading involves risk. This API provides access to real trading accounts and real money. Always test thoroughly in a sandbox environment before using in production.

---

*Last Updated: February 2026*  
*Documentation Format: Markdown*  
*Source: Schwab OpenAPI Specifications*
