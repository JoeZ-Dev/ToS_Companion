# Schwab Trader API – Internal Integration Documentation

**Product:** Trader API – Individual
**Environment:** Production
**Base URL:** `https://api.schwabapi.com/trader/v1`

---

## 1. Purpose

This document defines how our application authenticates with and interacts with the Charles Schwab Trader API. It is intended to be used as **internal, app-level documentation** and as a reference for implementation, maintenance, and future refactors.

---

## 2. High-Level Architecture

Our application acts as a **third-party OAuth 2.0 client** that accesses Schwab user accounts on behalf of an authenticated user.

Key characteristics:

* OAuth 2.0 Authorization Code (three‑legged flow)
* Explicit user consent via Schwab Login Micro Site (LMS)
* Short‑lived access tokens
* Medium‑lived refresh tokens
* Bearer token authorization on every API call

---

## 3. OAuth Roles (Normalized)

| Schwab Term          | Internal Meaning               |
| -------------------- | ------------------------------ |
| Resource Owner       | End user (Schwab client)       |
| OAuth Client         | Our registered Schwab app      |
| Authorization Server | Schwab OAuth service           |
| Resource Server      | Schwab Trader API              |
| User-Agent           | Our web or desktop application |

---

## 4. OAuth Token Characteristics

| Token Type    | Lifetime   | Notes                       |
| ------------- | ---------- | --------------------------- |
| Access Token  | 30 minutes | Required for all API calls  |
| Refresh Token | 7 days     | Used to renew access tokens |

Rules:

* Access tokens must be refreshed before expiry
* Refresh tokens expire after 7 days
* After refresh token expiry or invalidation, full OAuth flow is required

---

## 5. OAuth Flow Overview

1. Redirect user to Schwab authorization endpoint
2. User authenticates and grants consent
3. Schwab redirects back with authorization code
4. App exchanges code for access + refresh tokens
5. App calls Trader API using Bearer access token
6. App refreshes access token as needed
7. App re‑initiates OAuth after refresh token expiry

---

## 6. OAuth Step‑by‑Step Implementation

### Step 1 – User Authorization Redirect

**Endpoint**
`GET https://api.schwabapi.com/v1/oauth/authorize`

**Query Parameters**

| Name         | Description          |
| ------------ | -------------------- |
| client_id    | Schwab app client ID |
| redirect_uri | HTTPS callback URL   |

**Example**

```
https://api.schwabapi.com/v1/oauth/authorize?client_id=CLIENT_ID&redirect_uri=https://yourapp.com/callback
```

**Redirect Response**

```
https://yourapp.com/callback?code=AUTH_CODE&session=SESSION_ID
```

Notes:

* Redirect target may return a 404; this is expected
* The `code` query parameter is required for token exchange
* The authorization code must be URL‑decoded before use

---

### Step 2 – Exchange Authorization Code for Tokens

**Endpoint**
`POST https://api.schwabapi.com/v1/oauth/token`

**Headers**

```
Authorization: Basic base64(client_id:client_secret)
Content-Type: application/x-www-form-urlencoded
```

**Body**

```
grant_type=authorization_code
code=AUTH_CODE
redirect_uri=https://yourapp.com/callback
```

**Response**

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_in": 1800,
  "token_type": "Bearer",
  "scope": "api",
  "id_token": "JWT"
}
```

---

### Step 3 – Authorized API Calls

All Trader API calls must include the following header:

```
Authorization: Bearer ACCESS_TOKEN
```

---

### Step 4 – Refresh Access Token

**Endpoint**
`POST https://api.schwabapi.com/v1/oauth/token`

**Body**

```
grant_type=refresh_token
refresh_token=REFRESH_TOKEN
```

**Response**

```json
{
  "access_token": "NEW_ACCESS_TOKEN",
  "refresh_token": "NEW_REFRESH_TOKEN",
  "expires_in": 1800
}
```

Rules:

* Refresh token may be used before or after access token expiry
* After refresh token expiry (7 days), OAuth must restart
* Password resets invalidate refresh tokens

---

## 7. Trader API Domains

### Accounts

| Endpoint                      | Description                      |
| ----------------------------- | -------------------------------- |
| GET /accounts/accountNumbers  | Encrypted account number mapping |
| GET /accounts                 | All linked accounts              |
| GET /accounts/{accountNumber} | Single account details           |

---

### Orders

| Endpoint                              | Description                 |
| ------------------------------------- | --------------------------- |
| GET /orders                           | All orders across accounts  |
| GET /accounts/{account}/orders        | Orders for specific account |
| POST /accounts/{account}/previewOrder | Validate order              |
| POST /accounts/{account}/orders       | Place order                 |

---

### Transactions

| Endpoint                             | Description         |
| ------------------------------------ | ------------------- |
| GET /accounts/{account}/transactions | Transaction history |

---

## 8. Trading Constraints

### Supported Asset Types

* Equities (stocks and ETFs)
* Options

### Order Rate Limits

| Method              | Limit                                 |
| ------------------- | ------------------------------------- |
| PUT / POST / DELETE | 0–120 requests per minute per account |
| GET                 | Unthrottled                           |

Limits are configured per app during registration.

---

## 9. Order Instruction Rules

| Instruction   | Equity   | Option   |
| ------------- | -------- | -------- |
| BUY           | Accepted | Rejected |
| SELL          | Accepted | Rejected |
| SELL_SHORT    | Accepted | Rejected |
| BUY_TO_COVER  | Accepted | Rejected |
| BUY_TO_OPEN   | Rejected | Accepted |
| BUY_TO_CLOSE  | Rejected | Accepted |
| SELL_TO_OPEN  | Rejected | Accepted |
| SELL_TO_CLOSE | Rejected | Accepted |

---

## 10. Option Symbol Format

Format:

```
UNDERLYING(6) + EXPIRATION(YYMMDD) + C/P + STRIKE(8)
```

Example:

```
XYZ 210115C00050000
```

---

## 11. App Registration Constraints

* One API product per app
* Callback URLs must be HTTPS
* Multiple callback URLs allowed (comma‑separated)
* 255 character limit on callback list
* Localhost allowed: `https://127.0.0.1`

---

## 12. Operational Guidance

Recommended application behaviors:

* Secure storage of refresh tokens
* Automatic access token refresh prior to expiry
* Centralized OAuth error handling
* Cached account number mappings
* Rate‑limit aware order submission

---

## 13. Failure Modes & Recovery

| Scenario              | Required Action      |
| --------------------- | -------------------- |
| Access token expired  | Refresh token        |
| Refresh token expired | Restart OAuth        |
| User password reset   | Restart OAuth        |
| Order rate limit hit  | Backoff and retry    |
| Invalid instruction   | Reject before submit |

---

## 14. Open Design Decisions

Pending internal decisions:

* Token storage strategy
* Re‑authentication UX flow
* Mandatory vs optional order preview
* Account selection behavior post‑consent

---

**End of Document**
