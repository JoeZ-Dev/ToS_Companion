# joelab browser deployment

## Objective

Run ToS_Companion continuously on joelab and access it through a browser.

The browser is presentation only. Schwab REST/streaming, analysis, recording, persistence, and future trading actions remain server-side.

## Authentication boundary

`companion_auth` remains the only owner of Schwab OAuth authorization and refresh tokens.

The ToS_Companion service uses:

```text
TokenProvider -> AUTH_HELPER_URL -> companion_auth -> Schwab
```

The browser never receives Schwab access or refresh tokens.

Do not configure a second Schwab app or local OAuth token store for the web service.

## Suggested filesystem layout

```text
/srv/apps/tos-companion/
  .venv/
  .env
  <repository checkout>
```

Persistent application data continues to use the existing ToS_Companion paths under the service user's home directory, including:

```text
~/.tos_companion/
~/.tos_companion/recordings/
```

## Install/update

From the checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e '.[web]'
```

For a simple source deployment, future updates become:

```bash
git pull --ff-only
.venv/bin/pip install -e '.[web]'
sudo systemctl restart tos-companion
```

The browser then only needs a refresh.

## Run manually

```bash
AUTH_HELPER_URL=http://companion-auth.p3l.co \
TOS_COMPANION_HOST=127.0.0.1 \
TOS_COMPANION_PORT=8787 \
python -m momentum_companion.web
```

Open the service through the configured joelab reverse proxy.

## systemd

Copy and adapt:

```text
deploy/systemd/tos-companion.service.example
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tos-companion
sudo systemctl status tos-companion
```

## Reverse proxy/security

The application intentionally binds to `127.0.0.1` by default.

Do not expose port 8787 directly to the public internet.

Use the existing joelab reverse-proxy/access-control layer for HTTPS and authentication. This becomes especially important before browser order-entry controls are enabled.

The reverse proxy must support WebSocket upgrades for `/ws`.

## Current browser surface

Implemented on the browser-foundation feature branch:

- live server status;
- symbol selection;
- historical chart seed;
- live L1 quote updates;
- server-side 10-second bars;
- AE snapshot display;
- WebSocket reconnect;
- multi-symbol recorder controls;
- automatic recorder cutoff at 3:00 PM ET.

Recording continues when the browser is closed because the recorder belongs to the joelab runtime, not the browser session.

## Deliberately not enabled yet

- browser order submission;
- account/order management;
- public unauthenticated deployment;
- scanner;
- separate Schwab OAuth flow;
- automatic T&S dependency.

Those should remain out until the browser read/analysis/recording path is proven live on joelab.
