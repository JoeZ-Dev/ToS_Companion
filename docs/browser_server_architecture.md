# Browser/server architecture refactor

## Goal

Run the full ToS_Companion application continuously on `joelab` and access it from a browser.

This removes the current desktop development friction:
- rebuild locally;
- pull/copy updated code;
- relaunch the desktop application;
- repeat.

The desired operational model is a continuously running service where code is deployed once to joelab and the user simply refreshes the browser.

## Critical Schwab authentication constraint

`companion_auth` remains the **single owner of Schwab OAuth authorization and refresh tokens**.

The browser/server refactor must not introduce:
- a second Schwab application;
- a second refresh token;
- a separate browser OAuth flow;
- Schwab access tokens stored in browser storage;
- Schwab refresh tokens exposed to the frontend.

The ToS_Companion backend obtains access tokens through the existing `TokenProvider` / `companion_auth` mechanism.

The browser never receives a Schwab token.

## Target architecture

```text
Browser
   |
   | HTTPS + WebSocket
   v
ToS_Companion service on joelab
   |
   +-- headless CompanionSession
   +-- Schwab stream client
   +-- Schwab REST client
   +-- bar aggregation
   +-- indicators
   +-- analysis engine
   +-- setup state
   +-- LLM service
   +-- execution / trading gates
   +-- journal / SQLite
   +-- intraday recorder
   +-- future replay simulator
   |
   v
companion_auth
   |
   v
Schwab
```

## Main refactor

The current `UIController` combines presentation logic with substantial application behavior.

The primary architectural change is to split it into:

### 1. Headless application/session layer

A new headless service, conceptually `CompanionSession`, should own:
- active and watched symbols;
- Schwab connection state;
- live quotes;
- bar aggregation;
- historical bars;
- indicators;
- AE state;
- setup state;
- LLM state;
- trading gates;
- execution state;
- recorder state;
- journal integration.

It must not depend on PySide6 or Qt widgets.

### 2. Presentation adapters

Presentation becomes replaceable.

Possible adapters:
- existing PySide desktop UI;
- browser API/WebSocket adapter.

The browser migration should not require rewriting the core trading/analysis stack.

## Backend technology

Recommended backend:
- FastAPI;
- WebSocket endpoint for realtime state;
- REST endpoints for commands and slower data access.

The existing Python stack remains authoritative.

## Realtime WebSocket events

Likely server-to-browser event types include:
- `quote`;
- `forming_bar`;
- `completed_bar`;
- `analysis_snapshot`;
- `setup_state`;
- `llm_update`;
- `connection_state`;
- `trade_state`;
- `recorder_state`;
- `journal_event`.

The backend should maintain the Schwab connection regardless of browser connections.

Closing or refreshing the browser must not interrupt:
- Schwab streaming;
- recording;
- analysis;
- open application state.

## REST actions

Likely browser-to-server actions include:
- select/add/remove symbol;
- start recording;
- stop recording;
- load history;
- run analysis;
- update settings;
- read journal;
- read replay sessions;
- future replay controls.

If live trading remains enabled, order actions must remain server-side and go through existing safety gates.

## Charting

ToS_Companion already contains TradingView Lightweight Charts JavaScript assets.

The browser frontend should use Lightweight Charts directly rather than attempting to reproduce the Qt chart wrapper.

This is one of the easier portions of the browser migration.

## Multi-symbol state

The current desktop application is primarily single-active-symbol oriented.

The server model should move toward:
- one shared Schwab connection;
- several watched symbols;
- independent state per symbol;
- one or more symbols visible in browser tabs/panels.

Manual symbol selection remains acceptable. A scanner is out of scope for the initial browser refactor.

## Recorder integration

The intraday recorder becomes more useful once ToS_Companion is a continuous server.

Example workflow:
1. Add a momentum candidate at 8:15 AM.
2. Server begins recording.
3. Close the browser.
4. joelab continues recording and analyzing.
5. Recorder automatically stops at 3:00 PM ET.
6. Session is available later for replay.

Recording should not depend on an open browser session.

## Replay architecture compatibility

The refactor should establish a common market-event interface so both:
- live Schwab events;
- recorded replay events

can feed the same headless session/analysis engine.

This is important for future fill simulation and strategy validation.

## Deployment model

The confirmed joelab topology is Docker + Cloudflare Tunnel.

Target containers share the external `joelab-ingress` network:

```text
cloudflared
companion-auth
tos-companion
```

ToS_Companion resolves the existing auth helper internally as:

```text
http://companion-auth:8766
```

Cloudflare Tunnel should route the browser hostname directly to:

```text
http://tos-companion:8787
```

No host port needs to be published.

## Migration stages

### Stage 1: Extract headless state
Move business/application behavior out of Qt-specific `UIController` code into a headless session object.

### Stage 2: Preserve desktop behavior
Adapt the existing Qt UI to consume the new headless session so the extraction can be validated without simultaneously changing presentation technology.

### Stage 3: Add FastAPI
Expose headless state and actions over REST/WebSocket.

### Stage 4: Build browser UI
Implement:
- symbol controls;
- chart;
- connection status;
- AE state;
- setup state;
- LLM panel;
- recorder controls.

### Stage 5: Migrate trading controls
Only after the read/analysis path is stable, expose any existing live trading controls through server-side safety gates.

### Stage 6: Deploy continuously on joelab
Run the backend as a persistent service and access the application entirely through a browser.

### Stage 7: Add replay mode
Allow recorded sessions to feed the same headless application engine using a simulated clock.

## Non-goals for the first browser pass

Do not combine this refactor with:
- building a stock scanner;
- redesigning momentum strategy logic;
- validating new entry/exit rules;
- replacing `companion_auth`;
- creating a new Schwab application;
- rewriting all backend Python.

The browser project should first solve deployment friction and establish a clean long-running architecture.


## LLM runtime direction

The initial browser foundation inherited the desktop direct-API-key OpenAI client for compatibility. That is not the intended long-term joelab design.

The planned server implementation should use the same CLI-style OpenAI authentication/execution pattern used by the user's newer applications. The browser remains a thin client and must never receive OpenAI credentials. The current API-key path should remain transitional until the CLI-backed adapter is implemented and tested.
