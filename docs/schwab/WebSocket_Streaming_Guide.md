# Schwab API WebSocket Streaming Guide

## Overview

The Schwab API provides **real-time streaming data** via WebSocket connections. This allows you to receive live market data updates, account changes, and order status updates without constantly polling the REST API.

## Obtaining Streaming Credentials

WebSocket streaming credentials are obtained through the **User Preference** endpoint in the Trader API.

### Get User Preferences (Including Streamer Info)

**Endpoint:** `GET /trader/v1/userPreference`

**Authentication:** OAuth 2.0 Bearer token required

**Request:**
```bash
curl -X GET https://api.schwabapi.com/trader/v1/userPreference \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Response:**
```json
[
  {
    "accounts": [...],
    "streamerInfo": [
      {
        "streamerSocketUrl": "wss://streamer-api.schwab.com/ws",
        "schwabClientCustomerId": "CUSTOMER_ID",
        "schwabClientCorrelId": "CORRELATION_ID",
        "schwabClientChannel": "CHANNEL_ID",
        "schwabClientFunctionId": "FUNCTION_ID"
      }
    ],
    "offers": [...]
  }
]
```

### StreamerInfo Schema

The `StreamerInfo` object contains the credentials and connection details needed for WebSocket streaming:

| Property | Type | Description |
|----------|------|-------------|
| `streamerSocketUrl` | string | WebSocket server URL (typically `wss://streamer-api.schwab.com/ws`) |
| `schwabClientCustomerId` | string | Your unique customer identifier |
| `schwabClientCorrelId` | string | Correlation ID for request tracking |
| `schwabClientChannel` | string | Channel identifier |
| `schwabClientFunctionId` | string | Function identifier |

## Python Example: Getting Streaming Credentials

```python
import requests

def get_streaming_credentials(access_token):
    """
    Get WebSocket streaming credentials from Schwab API.
    
    Returns:
        dict: StreamerInfo object with connection details
    """
    url = 'https://api.schwabapi.com/trader/v1/userPreference'
    headers = {'Authorization': f'Bearer {access_token}'}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        user_prefs = response.json()
        
        # Extract streamer info from first preference object
        if user_prefs and len(user_prefs) > 0:
            streamer_info_list = user_prefs[0].get('streamerInfo', [])
            
            if streamer_info_list and len(streamer_info_list) > 0:
                return streamer_info_list[0]
    
    raise Exception(f"Failed to get streaming credentials: {response.status_code}")

# Usage
streaming_creds = get_streaming_credentials(access_token)
print(f"WebSocket URL: {streaming_creds['streamerSocketUrl']}")
```

## WebSocket Connection Setup

### Basic Connection Pattern

```python
import websocket
import json
import threading

class SchwabStreamer:
    def __init__(self, streamer_info, access_token):
        self.ws_url = streamer_info['streamerSocketUrl']
        self.customer_id = streamer_info['schwabClientCustomerId']
        self.correl_id = streamer_info['schwabClientCorrelId']
        self.channel = streamer_info['schwabClientChannel']
        self.function_id = streamer_info['schwabClientFunctionId']
        self.access_token = access_token
        self.ws = None
    
    def on_message(self, ws, message):
        """Handle incoming WebSocket messages"""
        data = json.loads(message)
        print(f"Received: {data}")
    
    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        print(f"Error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection close"""
        print(f"Connection closed: {close_status_code} - {close_msg}")
    
    def on_open(self, ws):
        """Handle WebSocket connection open"""
        print("WebSocket connection established")
        
        # Send login/authentication message
        login_msg = {
            "service": "ADMIN",
            "command": "LOGIN",
            "requestid": "1",
            "SchwabClientCustomerId": self.customer_id,
            "SchwabClientCorrelId": self.correl_id,
            "parameters": {
                "Authorization": self.access_token,
                "SchwabClientChannel": self.channel,
                "SchwabClientFunctionId": self.function_id
            }
        }
        
        ws.send(json.dumps(login_msg))
    
    def connect(self):
        """Establish WebSocket connection"""
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        # Run WebSocket in a separate thread
        ws_thread = threading.Thread(target=self.ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()
    
    def disconnect(self):
        """Close WebSocket connection"""
        if self.ws:
            self.ws.close()

# Usage
streamer = SchwabStreamer(streaming_creds, access_token)
streamer.connect()
```

## Streaming Data Types

While the specific streaming services and commands are not detailed in the OpenAPI specification, typical streaming capabilities include:

### Market Data Streams (Expected)
- **Level 1 Quotes** - Real-time bid/ask/last prices
- **Level 2 Data** - Market depth (order book)
- **Time & Sales** - Trade tick data
- **Chart Data** - Real-time candlestick updates
- **Options** - Real-time option chain updates
- **News** - Breaking news alerts

### Account Streams (Expected)
- **Account Activity** - Balance and position updates
- **Order Updates** - Order status changes
- **Execution Reports** - Trade confirmations

## Important Notes

### Authentication
1. **Initial authentication** is done via the OAuth 2.0 access token
2. **Streamer credentials** must be obtained from `/userPreference` endpoint
3. Credentials may have a limited lifetime and need to be refreshed

### Connection Management

```python
import time

class ManagedStreamer(SchwabStreamer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.should_reconnect = True
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5  # seconds
    
    def on_close(self, ws, close_status_code, close_msg):
        """Auto-reconnect on disconnect"""
        super().on_close(ws, close_status_code, close_msg)
        
        if self.should_reconnect:
            attempt = 0
            while attempt < self.max_reconnect_attempts:
                attempt += 1
                print(f"Reconnecting... Attempt {attempt}/{self.max_reconnect_attempts}")
                time.sleep(self.reconnect_delay)
                
                try:
                    self.connect()
                    break
                except Exception as e:
                    print(f"Reconnection failed: {e}")
    
    def stop(self):
        """Stop auto-reconnection and close"""
        self.should_reconnect = False
        self.disconnect()
```

### Subscription Management

```python
def subscribe_to_quotes(self, symbols):
    """
    Subscribe to Level 1 quote data.
    
    Args:
        symbols: List of ticker symbols (e.g., ['AAPL', 'MSFT'])
    """
    if not self.ws:
        raise Exception("WebSocket not connected")
    
    subscribe_msg = {
        "service": "QUOTE",
        "command": "SUBS",
        "requestid": "2",
        "SchwabClientCustomerId": self.customer_id,
        "SchwabClientCorrelId": self.correl_id,
        "parameters": {
            "keys": ",".join(symbols),
            "fields": "0,1,2,3,4,5,6,7,8"  # Field IDs for desired data
        }
    }
    
    self.ws.send(json.dumps(subscribe_msg))

def unsubscribe_from_quotes(self, symbols):
    """Unsubscribe from quote data"""
    unsubscribe_msg = {
        "service": "QUOTE",
        "command": "UNSUBS",
        "requestid": "3",
        "SchwabClientCustomerId": self.customer_id,
        "SchwabClientCorrelId": self.correl_id,
        "parameters": {
            "keys": ",".join(symbols)
        }
    }
    
    self.ws.send(json.dumps(unsubscribe_msg))
```

## Complete Working Example

```python
import websocket
import json
import time
from threading import Thread

class SchwabWebSocketClient:
    def __init__(self, access_token):
        self.access_token = access_token
        self.streaming_creds = None
        self.ws = None
        self.connected = False
    
    def initialize(self):
        """Get streaming credentials and connect"""
        # Get streaming credentials
        self.streaming_creds = self.get_streaming_credentials()
        
        # Establish WebSocket connection
        self.connect()
    
    def get_streaming_credentials(self):
        """Fetch streaming credentials from API"""
        import requests
        
        url = 'https://api.schwabapi.com/trader/v1/userPreference'
        headers = {'Authorization': f'Bearer {self.access_token}'}
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        user_prefs = response.json()
        return user_prefs[0]['streamerInfo'][0]
    
    def on_open(self, ws):
        """Handle connection open"""
        print("WebSocket connected!")
        self.connected = True
        
        # Authenticate
        login_msg = {
            "service": "ADMIN",
            "command": "LOGIN",
            "requestid": "0",
            "SchwabClientCustomerId": self.streaming_creds['schwabClientCustomerId'],
            "SchwabClientCorrelId": self.streaming_creds['schwabClientCorrelId'],
            "parameters": {
                "Authorization": self.access_token,
                "SchwabClientChannel": self.streaming_creds['schwabClientChannel'],
                "SchwabClientFunctionId": self.streaming_creds['schwabClientFunctionId']
            }
        }
        ws.send(json.dumps(login_msg))
    
    def on_message(self, ws, message):
        """Handle incoming messages"""
        data = json.loads(message)
        
        # Process different message types
        if data.get('service') == 'ADMIN':
            if data.get('command') == 'LOGIN':
                print("Login successful!")
                # Subscribe to data after successful login
                self.subscribe_quotes(['AAPL', 'MSFT', 'GOOGL'])
        else:
            # Handle market data updates
            print(f"Market data: {data}")
    
    def on_error(self, ws, error):
        """Handle errors"""
        print(f"WebSocket error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        """Handle connection close"""
        print(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.connected = False
    
    def connect(self):
        """Establish WebSocket connection"""
        ws_url = self.streaming_creds['streamerSocketUrl']
        
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        # Run in background thread
        ws_thread = Thread(target=self.ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()
    
    def subscribe_quotes(self, symbols):
        """Subscribe to real-time quotes"""
        if not self.connected:
            raise Exception("Not connected to WebSocket")
        
        msg = {
            "service": "QUOTE",
            "command": "SUBS",
            "requestid": "1",
            "SchwabClientCustomerId": self.streaming_creds['schwabClientCustomerId'],
            "SchwabClientCorrelId": self.streaming_creds['schwabClientCorrelId'],
            "parameters": {
                "keys": ",".join(symbols),
                "fields": "0,1,2,3,4,5,6,7,8"
            }
        }
        
        self.ws.send(json.dumps(msg))
        print(f"Subscribed to quotes for: {symbols}")
    
    def disconnect(self):
        """Close WebSocket connection"""
        if self.ws:
            self.ws.close()

# Usage Example
if __name__ == "__main__":
    # Assume you have a valid access token
    access_token = "YOUR_ACCESS_TOKEN"
    
    # Create and initialize client
    client = SchwabWebSocketClient(access_token)
    client.initialize()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        client.disconnect()
```

## Best Practices

### 1. Token Management
```python
# Refresh access token before it expires
def refresh_token_if_needed(token_manager):
    if not token_manager.is_token_valid():
        new_token = token_manager.refresh()
        # Update WebSocket with new token
        return new_token
    return token_manager.get_valid_token()
```

### 2. Heartbeat/Ping-Pong
```python
# Implement periodic heartbeat to keep connection alive
def send_heartbeat(ws):
    heartbeat_msg = {
        "service": "ADMIN",
        "command": "QOS",
        "requestid": "heartbeat",
        "parameters": {
            "qoslevel": 0
        }
    }
    ws.send(json.dumps(heartbeat_msg))
```

### 3. Error Recovery
```python
# Implement exponential backoff for reconnection
def reconnect_with_backoff(max_attempts=5):
    for attempt in range(max_attempts):
        try:
            connect()
            return True
        except Exception as e:
            wait_time = min(2 ** attempt, 60)  # Max 60 seconds
            time.sleep(wait_time)
    return False
```

## Rate Limits and Quotas

- Monitor connection limits per account
- Avoid excessive subscribe/unsubscribe operations
- Implement proper throttling for requests

## Troubleshooting

### Common Issues

**Connection Refused:**
- Verify OAuth token is valid
- Check streaming credentials are current
- Ensure WebSocket URL is correct

**Authentication Failed:**
- Refresh streaming credentials from `/userPreference`
- Verify all credential fields are being sent
- Check OAuth token hasn't expired

**Disconnections:**
- Implement reconnection logic
- Check network connectivity
- Monitor token expiration

**No Data Received:**
- Verify subscription was successful
- Check symbol format is correct
- Ensure market is open (for market data)

## Additional Resources

- [Schwab Developer Portal](https://developer.schwab.com)
- [WebSocket Protocol RFC 6455](https://tools.ietf.org/html/rfc6455)
- [Python websocket-client library](https://github.com/websocket-client/websocket-client)

## Security Considerations

⚠️ **Important:**
- Never log or expose streaming credentials
- Rotate OAuth tokens regularly
- Use secure WebSocket (wss://) connections only
- Implement proper error handling to avoid credential leaks

---

**Note:** The specific streaming message formats, field IDs, and service types may vary. Consult the official Schwab streaming documentation or developer support for the complete streaming protocol specification.

*Last Updated: February 2026*
