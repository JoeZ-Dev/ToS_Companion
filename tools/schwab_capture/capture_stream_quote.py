import base64
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

import requests
import websocket
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ["SCHWAB_CLIENT_ID"]
CLIENT_SECRET = os.environ["SCHWAB_CLIENT_SECRET"]
REDIRECT_URI = os.environ.get("SCHWAB_REDIRECT_URI", "https://companion-auth.p3l.co/callback")
SCOPE = os.environ.get("SCHWAB_SCOPE", "readonly")
SYMBOL = os.environ.get("SYMBOL", "AAPL")
STREAM_SERVICES = [s.strip() for s in os.environ.get(
    "SCHWAB_STREAM_SERVICES",
    "QUOTE,LEVELONE_EQUITIES,CHART_EQUITY"
).split(",") if s.strip()]


AUTH_BASE = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
USER_PREF_URL = "https://api.schwabapi.com/trader/v1/userPreference"

# --- OAuth callback server (captures ?code=...&state=...) ---

auth_code_holder = {"code": None, "state": None, "error": None}

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urlparse(self.path)
        if q.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        params = parse_qs(q.query)
        if "error" in params:
            auth_code_holder["error"] = params.get("error", ["unknown"])[0]
        else:
            auth_code_holder["code"] = params.get("code", [None])[0]
            auth_code_holder["state"] = params.get("state", [None])[0]

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"You can close this window and return to the terminal.")

    def log_message(self, format, *args):
        # Silence default logging to avoid leaking query params into logs
        return

def start_callback_server(host="127.0.0.1", port=8765):
    httpd = HTTPServer((host, port), CallbackHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd

def build_auth_url(state: str) -> str:
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
    }
    return f"{AUTH_BASE}?{urlencode(params)}"

def exchange_code_for_tokens(code: str) -> dict:
    creds = f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    b64 = base64.b64encode(creds).decode()

    headers = {
        "Authorization": f"Basic {b64}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    r = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    r.raise_for_status()
    return r.json()

def get_user_preference(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(USER_PREF_URL, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def redact_streamer_info(si: dict) -> dict:
    # Keep structure, redact identifiers
    redacted = dict(si)
    for k in ["schwabClientCustomerId", "schwabClientCorrelId", "schwabClientChannel", "schwabClientFunctionId"]:
        if k in redacted and redacted[k] is not None:
            redacted[k] = "<REDACTED>"
    return redacted

def ws_capture(streamer_info: dict, access_token: str, seconds: int = 15):
    ws_url = streamer_info["streamerSocketUrl"]

    # NOTE: Schwab streaming auth expects the raw access token string as "Authorization" parameter (per docs),
    # not "Bearer ...". If your connection fails, try adding "Bearer " prefix.
    login_msg = {
        "service": "ADMIN",
        "command": "LOGIN",
        "requestid": "1",
        "SchwabClientCustomerId": streamer_info["schwabClientCustomerId"],
        "SchwabClientCorrelId": streamer_info["schwabClientCorrelId"],
        "parameters": {
            "Authorization": access_token,
            "SchwabClientChannel": streamer_info["schwabClientChannel"],
            "SchwabClientFunctionId": streamer_info["schwabClientFunctionId"],
        },
    }

    # QUOTE subscription fields are the unknown we want to learn.
    # We'll subscribe with a broad "fields" list. The returned payload reveals mapping/keys.
    subs_msgs = []
    req_id = 2
    for svc in STREAM_SERVICES:
        subs_msgs.append({
            "service": svc,
            "command": "SUBS",
            "requestid": str(req_id),
            "SchwabClientCustomerId": streamer_info["schwabClientCustomerId"],
            "SchwabClientCorrelId": streamer_info["schwabClientCorrelId"],
            "parameters": {
                "keys": SYMBOL,
                "fields": "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15"
            },
        })
        req_id += 1


    captured = {"messages": []}

    def on_open(ws):
        ws.send(json.dumps(login_msg))
        time.sleep(0.5)

        qos_msg = {
            "service": "ADMIN",
            "command": "QOS",
            "requestid": "1a",
            "SchwabClientCustomerId": streamer_info["schwabClientCustomerId"],
            "SchwabClientCorrelId": streamer_info["schwabClientCorrelId"],
            "parameters": {"qoslevel": 0},
        }
        ws.send(json.dumps(qos_msg))
        time.sleep(0.25)

        for m in subs_msgs:
            ws.send(json.dumps(m))
            time.sleep(0.25)


    def on_message(ws, message):
        # Print raw message but redact obvious tokens if they appear (shouldn't)
        captured["messages"].append(message)
        print(message)

    def on_error(ws, err):
        print(f"WS error: {err}")

    def on_close(ws, code, msg):
        print(f"WS closed: {code} {msg}")

    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
    t = threading.Thread(target=ws.run_forever, daemon=True)
    t.start()

    time.sleep(seconds)
    ws.close()
    return captured

def main():
    # Start callback server
    httpd = start_callback_server(host="0.0.0.0", port=8765)

    # Build auth URL
    state = "CAPTURE_STATE_123"  # For capture only; you can randomize if you want
    auth_url = build_auth_url(state)

    print("\n1) Open this URL in a browser and complete Schwab login/consent:\n")
    print(auth_url)
    print("\nWaiting for OAuth redirect to /callback ...\n")

    # Wait for code
    start = time.time()
    while time.time() - start < 180:
        if auth_code_holder["error"]:
            raise RuntimeError(f"OAuth error: {auth_code_holder['error']}")
        if auth_code_holder["code"]:
            break
        time.sleep(0.25)

    if not auth_code_holder["code"]:
        raise RuntimeError("Timed out waiting for OAuth callback.")

    if auth_code_holder["state"] != state:
        raise RuntimeError("State mismatch. Aborting.")

    # Exchange tokens
    tokens = exchange_code_for_tokens(auth_code_holder["code"])
    access_token = tokens["access_token"]

    # Get streamer info
    prefs = get_user_preference(access_token)

    # Handle Schwab returning either a list[dict] or a dict wrapper
    if isinstance(prefs, list):
        root = prefs[0] if prefs else None
    elif isinstance(prefs, dict):
        # Some responses wrap the list in a top-level key; try common patterns
        if "accounts" in prefs or "streamerInfo" in prefs:
            root = prefs
        elif "data" in prefs and isinstance(prefs["data"], list) and prefs["data"]:
            root = prefs["data"][0]
        else:
            root = None
    else:
        root = None

    if not root:
        print("userPreference unexpected shape:")
        print(json.dumps(prefs, indent=2)[:4000])
        raise RuntimeError("userPreference response shape unexpected")

    if "streamerInfo" not in root or not root["streamerInfo"]:
        print("userPreference missing streamerInfo:")
        print(json.dumps(root, indent=2)[:4000])
        raise RuntimeError("No streamerInfo found in userPreference response.")

    streamer_info = root["streamerInfo"][0]

    print("\n2) StreamerInfo (redacted):")
    print(json.dumps(redact_streamer_info(streamer_info), indent=2))

    print("\n3) Capturing QUOTE stream raw messages for 15 seconds...\n")
    captured = ws_capture(streamer_info, access_token, seconds=15)

    # Save captured messages locally (do NOT commit)
    out_path = "captured_quote_messages.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for m in captured["messages"]:
            f.write(m.strip() + "\n")

    print(f"\nSaved raw messages to {out_path} (DO NOT COMMIT).")
    httpd.shutdown()

if __name__ == "__main__":
    main()
