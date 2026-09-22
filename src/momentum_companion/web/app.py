from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from momentum_companion.runtime import CompanionRuntime


STATIC_DIR = Path(__file__).with_name("static")
class RecordingRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class RecordingSymbolRequest(BaseModel):
    symbol: str


LIGHTWEIGHT_CHARTS_JS = (
    Path(__file__).resolve().parents[1]
    / "ui"
    / "assets"
    / "lightweight-charts.standalone.production.js"
)


def create_app(runtime: CompanionRuntime | None = None) -> FastAPI:
    companion = runtime or CompanionRuntime()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        companion.start()
        try:
            yield
        finally:
            companion.stop()

    app = FastAPI(
        title="ToS Companion",
        version="0.1.0-web",
        lifespan=lifespan,
    )
    app.state.runtime = companion
    llm_runs: set[str] = set()
    llm_runs_lock = threading.RLock()

    no_store = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers=no_store)

    @app.get("/app.js")
    @app.get("/app-20260922.js")
    @app.get("/app-20260922-3.js")
    @app.get("/app-20260922-4.js")
    @app.get("/app-20260922-5.js")
    @app.get("/app-20260922-6.js")
    @app.get("/app-20260922-7.js")
    @app.get("/app-20260922-8.js")
    @app.get("/app-20260922-9.js")
    @app.get("/app-20260922-10.js")
    @app.get("/app-20260922-11.js")
    def app_js() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "app.js",
            media_type="application/javascript",
            headers=no_store,
        )

    @app.get("/styles.css")
    @app.get("/styles-20260922.css")
    @app.get("/styles-20260922-2.css")
    @app.get("/styles-20260922-3.css")
    @app.get("/styles-20260922-4.css")
    @app.get("/styles-20260922-5.css")
    def styles() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "styles.css",
            media_type="text/css",
            headers=no_store,
        )

    @app.get("/vendor/lightweight-charts.js")
    @app.get("/vendor/lightweight-charts-20260922.js")
    def lightweight_charts() -> FileResponse:
        return FileResponse(
            LIGHTWEIGHT_CHARTS_JS,
            media_type="application/javascript",
            headers=no_store,
        )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        state = companion.snapshot()
        return {
            "ok": True,
            "connection_state": state["connection_state"],
            "active_symbol": state["active_symbol"],
            "auth_owner": "companion_auth",
        }

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return companion.snapshot()

    @app.get("/api/readiness")
    def readiness() -> dict[str, Any]:
        return companion.readiness()

    @app.get("/api/auth/status")
    def auth_status() -> dict[str, Any]:
        return companion.auth_status()

    @app.post("/api/symbol/{symbol}")
    def select_symbol(symbol: str) -> dict[str, Any]:
        try:
            return companion.select_symbol(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"symbol selection failed: {type(exc).__name__}") from exc

    @app.post("/api/recording/start")
    def start_recording(request: RecordingRequest) -> dict[str, Any]:
        try:
            return companion.start_recording(request.symbols)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/recording/symbol")
    def add_recording_symbol(request: RecordingSymbolRequest) -> dict[str, Any]:
        try:
            return companion.add_recording_symbol(request.symbol)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/recording/symbol/{symbol}")
    def remove_recording_symbol(symbol: str) -> dict[str, Any]:
        try:
            return companion.remove_recording_symbol(symbol)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/recording/stop")
    def stop_recording() -> dict[str, Any]:
        return companion.stop_recording(reason="browser_stop")

    @app.post("/api/llm/run/{symbol}", status_code=202)
    def run_llm(symbol: str) -> dict[str, Any]:
        normalized = companion.session.normalize_symbol(symbol)
        if not normalized:
            raise HTTPException(status_code=400, detail="symbol is required")

        state = companion.snapshot()
        symbol_state = state.get("symbols", {}).get(normalized)
        if not symbol_state:
            raise HTTPException(status_code=400, detail=f"no state available for {normalized}")
        if not isinstance(symbol_state.get("ae_snapshot"), dict):
            raise HTTPException(status_code=400, detail=f"no AE snapshot available for {normalized}")

        with llm_runs_lock:
            if normalized in llm_runs:
                return {
                    "accepted": True,
                    "symbol": normalized,
                    "already_running": True,
                }
            llm_runs.add(normalized)

        def worker() -> None:
            try:
                companion.run_llm(normalized)
            except Exception as exc:
                companion.session.update_llm_output(
                    normalized,
                    {
                        "error": f"LLM analysis failed: {type(exc).__name__}: {exc}",
                        "stock_bias": "NO_EDGE",
                        "setups": [],
                    },
                )
            finally:
                with llm_runs_lock:
                    llm_runs.discard(normalized)

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"tos-llm-{normalized}",
        ).start()

        return {
            "accepted": True,
            "symbol": normalized,
            "already_running": False,
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)

        def subscriber(event: dict[str, Any]) -> None:
            def enqueue() -> None:
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

            loop.call_soon_threadsafe(enqueue)

        unsubscribe = companion.session.subscribe(subscriber)
        try:
            await websocket.send_json(
                {"type": "snapshot", "payload": companion.snapshot()}
            )
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()

    return app
