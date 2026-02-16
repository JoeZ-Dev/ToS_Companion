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
    "LEVELONE_EQUITIES,CHART_EQUITY"
).split(",") if s.strip()]

AUTH_BASE = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
USER_PREF_URL = "https://api.schwabapi.com/trader/v1/userPreference"

TOKENS_PATH = os.path.join(os.path.dirname(__file__), ".tokens.json")

auth_code_holder = {"code": None, "state": None, "error": None}

class CallbackHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.do_GET()

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
        self.wfile.write(b"You can close this window and return to terminal.")

    def log_message(self, format, *args):
        return

def start_callback_server(host="0.0.0.0", port=8765):
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

def _basic_auth_header() -> dict:
    creds = f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    b64 = base64.b64encode(creds).decode()
    return {"Authorization": f"Basic {b64}"}

def exchange_code_for_tokens(code: str) -> dict:
    headers = {
        **_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    r = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    r.raise_for_status()
    tok = r.json()
    tok["expires_at"] = int(time.time()) + int(tok.get("expires_in", 0)) - 30
    return tok

def refresh_access_token(refresh_token: str) -> dict:
    headers = {
        **_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    r = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    r.raise_for_status()
    tok = r.json()
    tok["refresh_token"] = tok.get("refresh_token", refresh_token)  # keep old if not returned
    tok["expires_at"] = int(time.time()) + int(tok.get("expires_in", 0)) - 30
    return tok

def load_tokens() -> dict | None:
    if not os.path.exists(TOKENS_PATH):
        return None
    with open(TOKENS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_tokens(tok: dict) -> None:
    with open(TOKENS_PATH, "w", encoding="utf-8") as f:
        json.dump(tok, f, indent=2)

def get_valid_access_token() -> str:
    tok = load_tokens()
    now = int(time.time())
    if tok and tok.get("access_token") and tok.get("expires_at", 0) > now:
        return tok["access_token"]

    if tok and tok.get("refresh_token"):
        new_tok = refresh_access_token(tok["refresh_token"])
        save_tokens(new_tok)
        return new_tok["access_token"]

    # Need interactive auth once
    httpd = start_callback_server(host="0.0.0.0", port=8765)
    state = "CAPTURE_STATE_123"
    print("\nOpen this URL and complete login/consent:\n")
    print(build_auth_url(state))
    print("\nWaiting for OAuth redirect to /callback ...\n")

    start = time.time()
    while time.time() - start < 180:
        if auth_code_holder["error"]:
            httpd.shutdown()
            raise RuntimeError(f"OAuth error: {auth_code_holder['error']}")
        if auth_code_holder["code"]:
            break
        time.sleep(0.25)

    if not auth_code_holder["code"]:
        httpd.shutdown()
        raise RuntimeError("Timed out waiting for OAuth callback.")
    if auth_code_holder["state"] != state:
        httpd.shutdown()
        raise RuntimeError("State mismatch. Aborting.")

    new_tok = exchange_code_for_tokens(auth_code_holder["code"])
    save_tokens(new_tok)
    httpd.shutdown()
    return new_tok["access_token"]

def get_user_preference(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(USER_PREF_URL, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def extract_streamer_info(prefs):
    # handle list or dict shapes
    if isinstance(prefs, list) and prefs:
        root = prefs[0]
    elif isinstance(prefs, dict):
        root = prefs
    else:
        raise RuntimeError("userPreference unexpected response shape")
    if "streamerInfo" not in root or not root["streamerInfo"]:
        raise RuntimeError("No streamerInfo in userPreference response")
    return root["streamerInfo"][0]

def ws_capture(streamer_info: dict, access_token: str, seconds: int = 20):
    ws_url = streamer_info["streamerSocketUrl"]

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
        time.sleep(0.4)
        for m in subs_msgs:
            ws.send(json.dumps(m))
            time.sleep(0.2)

    def on_message(ws, message):
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
    access_token = get_valid_access_token()
    prefs = get_user_preference(access_token)
    streamer_info = extract_streamer_info(prefs)

    print("\nStreamer socket:", streamer_info.get("streamerSocketUrl"))
    print("Capturing streaming for", SYMBOL, "services:", ",".join(STREAM_SERVICES), "\n")

    captured = ws_capture(streamer_info, access_token, seconds=20)

    out_path = os.path.join(os.path.dirname(__file__), "captured_stream_messages.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for m in captured["messages"]:
            f.write(m.strip() + "\n")
    print("\nSaved:", out_path)

if __name__ == "__main__":
    main()

