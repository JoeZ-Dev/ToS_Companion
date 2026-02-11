# Schwab API OAuth 2.0 Authentication Guide

## Overview

The Schwab API uses OAuth 2.0 Authorization Code Flow (Three-Legged OAuth) for authentication and authorization. This security model ensures that your application can access user data only with explicit user consent.

## OAuth Flow Participants

1. **Resource Owner (User)** - The end user who owns the data
2. **User Agent (3rd-party application)** - Your application that needs access to user data
3. **OAuth Client (Dev Portal "App")** - Your registered application credentials
4. **Authorization Server** - Schwab's OAuth server that handles authentication
5. **Resource Server** - Schwab's API servers hosting protected resources

## Prerequisites

Before implementing OAuth authentication, you need:

1. **App Key (Client ID)** - Identifies your application
2. **App Secret (Client Secret)** - Authenticates your application
3. **Redirect URI** - Where users are redirected after authorization

> **Security Note:** Keep your Client Secret secure. Never expose it in client-side code or public repositories.

## OAuth 2.0 Authorization Code Flow

### Step 1: Initiate Authorization Request

Direct the user to Schwab's authorization endpoint:

```
GET /oauth/authorize
```

**URL:** `https://api.schwabapi.com/v1/oauth/authorize`

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | Yes | Your App Key from the Developer Portal |
| `redirect_uri` | Yes | Must match the URI registered in your app |
| `response_type` | Yes | Set to `code` for authorization code flow |
| `scope` | Optional | Space-separated list of permission scopes |
| `state` | Recommended | Random string to prevent CSRF attacks |

**Example Request:**

```
https://api.schwabapi.com/v1/oauth/authorize?
  client_id=YOUR_APP_KEY&
  redirect_uri=https://your-app.com/callback&
  response_type=code&
  state=RANDOM_STATE_STRING
```

### Step 2: User Authentication and Consent

1. The Authorization Server directs the Resource Owner to the Login Management System (LMS)
2. User completes Customer Authentication Gateway (CAG) activities
3. User provides consent for your application to access their data
4. LMS passes authorization details to OAuth server

### Step 3: Authorization Code Callback

After user consent, the Authorization Server redirects back to your `redirect_uri` with:

**Parameters in redirect:**

- `code` - The authorization code (short-lived, single-use)
- `state` - The same state value you provided (verify this matches!)

**Example Callback:**

```
https://your-app.com/callback?
  code=AUTHORIZATION_CODE&
  state=RANDOM_STATE_STRING
```

**Important:** 
- Validate that the `state` parameter matches what you sent
- Extract the `code` value immediately
- The authorization code expires quickly (typically within minutes)

### Step 4: Exchange Code for Access Token

Make a POST request to exchange the authorization code for an access token:

```
POST /oauth/token
```

**URL:** `https://api.schwabapi.com/v1/oauth/token`

**Headers:**

```
Content-Type: application/x-www-form-urlencoded
Authorization: Basic BASE64(client_id:client_secret)
```

**Body Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `grant_type` | Yes | Set to `authorization_code` |
| `code` | Yes | The authorization code from Step 3 |
| `redirect_uri` | Yes | Must match the original redirect URI |

**Example Request:**

```bash
curl -X POST https://api.schwabapi.com/v1/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Authorization: Basic BASE64_ENCODED_CREDENTIALS" \
  -d "grant_type=authorization_code" \
  -d "code=AUTHORIZATION_CODE" \
  -d "redirect_uri=https://your-app.com/callback"
```

**Response:**

```json
{
  "access_token": "ACCESS_TOKEN_VALUE",
  "refresh_token": "REFRESH_TOKEN_VALUE",
  "token_type": "Bearer",
  "expires_in": 1800,
  "scope": "api"
}
```

**Response Fields:**

- `access_token` - Use this to make API requests
- `refresh_token` - Use this to get new access tokens
- `token_type` - Always "Bearer"
- `expires_in` - Token lifetime in seconds (typically 30 minutes)
- `scope` - Granted permissions

### Step 5: Make API Requests

Include the access token in the Authorization header:

```
Authorization: Bearer YOUR_ACCESS_TOKEN
```

**Example API Request:**

```bash
curl -X GET https://api.schwabapi.com/trader/v1/accounts \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Step 6: Token Refresh

When the access token expires, use the refresh token to obtain a new one:

```
POST /oauth/token
```

**Headers:**

```
Content-Type: application/x-www-form-urlencoded
Authorization: Basic BASE64(client_id:client_secret)
```

**Body Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `grant_type` | Yes | Set to `refresh_token` |
| `refresh_token` | Yes | The refresh token from the original authorization |

**Example Request:**

```bash
curl -X POST https://api.schwabapi.com/v1/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Authorization: Basic BASE64_ENCODED_CREDENTIALS" \
  -d "grant_type=refresh_token" \
  -d "refresh_token=YOUR_REFRESH_TOKEN"
```

**Response:**

```json
{
  "access_token": "NEW_ACCESS_TOKEN",
  "refresh_token": "NEW_REFRESH_TOKEN",
  "token_type": "Bearer",
  "expires_in": 1800,
  "scope": "api"
}
```

## Token Management Best Practices

### Access Tokens

- **Lifetime:** Typically 30 minutes (1800 seconds)
- **Storage:** Store securely, never in client-side code
- **Usage:** Include in every API request
- **Expiration:** Check if token is valid before each request
- **Handling:** Request new token when it expires

### Refresh Tokens

- **Lifetime:** Typically 7 days
- **Storage:** Store securely in server-side database
- **Usage:** Exchange for new access tokens
- **Rotation:** Some implementations provide new refresh tokens
- **Security:** Treat with same care as passwords

## Security Considerations

### Protecting Credentials

1. **Never expose Client Secret in:**
   - Client-side JavaScript
   - Mobile apps
   - Public repositories
   - Browser storage

2. **Use environment variables for:**
   - Client ID
   - Client Secret
   - Redirect URIs

3. **Implement secure storage for:**
   - Access tokens
   - Refresh tokens
   - User session data

### State Parameter

Always use the `state` parameter to prevent CSRF attacks:

1. Generate a random, unique string for each authorization request
2. Store it in the user's session
3. Verify it matches when handling the callback
4. Reject the authorization if state doesn't match

### HTTPS

- All OAuth endpoints must use HTTPS
- Never transmit tokens over HTTP
- Ensure your redirect URI uses HTTPS

## Error Handling

### Common OAuth Errors

| Error Code | Description | Resolution |
|------------|-------------|------------|
| `invalid_request` | Malformed request | Check required parameters |
| `invalid_client` | Client authentication failed | Verify Client ID and Secret |
| `invalid_grant` | Authorization code invalid/expired | Request new authorization |
| `unauthorized_client` | Client not authorized | Check app permissions |
| `unsupported_grant_type` | Invalid grant_type | Use `authorization_code` or `refresh_token` |
| `invalid_scope` | Invalid scope requested | Check available scopes |

### Token Expiration Handling

```python
# Pseudocode example
def make_api_request(endpoint):
    if is_token_expired(access_token):
        if is_refresh_token_valid(refresh_token):
            refresh_access_token()
        else:
            redirect_to_authorization()
    
    return call_api(endpoint, access_token)
```

## Implementation Checklist

- [ ] Register application in Schwab Developer Portal
- [ ] Securely store Client ID and Client Secret
- [ ] Configure redirect URI(s)
- [ ] Implement authorization request with state parameter
- [ ] Handle authorization callback and validate state
- [ ] Exchange authorization code for tokens
- [ ] Securely store access and refresh tokens
- [ ] Implement token expiration checking
- [ ] Implement token refresh logic
- [ ] Handle OAuth error responses
- [ ] Use HTTPS for all requests
- [ ] Never expose tokens in logs or error messages

## Rate Limiting

Be aware of rate limits when making API requests:

- Check response headers for rate limit information
- Implement exponential backoff for retries
- Cache responses when appropriate
- Use refresh tokens judiciously

## Additional Resources

- [OAuth 2.0 RFC 6749](https://tools.ietf.org/html/rfc6749)
- [OAuth 2.0 Security Best Practices](https://tools.ietf.org/html/draft-ietf-oauth-security-topics)
- Schwab Developer Portal Documentation

## Support

For OAuth implementation issues:

1. Check the error response details
2. Review the OAuth flow sequence diagram
3. Verify all credentials and URIs match your app registration
4. Contact Schwab Developer Support if issues persist
