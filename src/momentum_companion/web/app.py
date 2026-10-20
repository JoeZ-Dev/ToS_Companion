from __future__ import annotations

import asyncio
from bisect import bisect_left, bisect_right
from functools import lru_cache
from contextlib import asynccontextmanager
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from momentum_companion.replay import ReplayEngine
from momentum_companion.clients.stream_mapping import LevelOneCache
from momentum_companion.runtime import CompanionRuntime
from momentum_companion.web.admin_access import AdminAccessVerifier


STATIC_DIR = Path(__file__).with_name("static")
class RecordingRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class RecordingSymbolRequest(BaseModel):
    symbol: str


class ReplayLoadRequest(BaseModel):
    session_id: str
    symbol: str


class ReplayPlayRequest(BaseModel):
    speed: int | str = 1


class ReplayStepRequest(BaseModel):
    count: int = 1


class ReplaySeekRequest(BaseModel):
    cursor: int


class ReplayInspectRequest(BaseModel):
    session_id: str
    symbol: str
    cursor: int | None = None
    timestamp_ms: int | None = None


class ReviewWindowRequest(BaseModel):
    session_id: str
    symbol: str
    start_ms: int | None = None
    end_ms: int | None = None


class ReviewL1WindowRequest(BaseModel):
    session_id: str
    symbol: str
    start_ms: int
    end_ms: int


LIGHTWEIGHT_CHARTS_JS = (
    Path(__file__).resolve().parents[1]
    / "ui"
    / "assets"
    / "lightweight-charts.standalone.production.js"
)


def create_app(
    runtime: CompanionRuntime | None = None,
    *,
    replay_engine: ReplayEngine | None = None,
    admin_authorizer: Any | None = None,
) -> FastAPI:
    companion = runtime or CompanionRuntime()
    replay = replay_engine or ReplayEngine(
        recordings_root=Path.home() / ".tos_companion" / "recordings"
    )
    admin_access = admin_authorizer or AdminAccessVerifier()

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

    def require_admin(request: Request) -> None:
        assertion = request.headers.get("Cf-Access-Jwt-Assertion")
        authorize = getattr(admin_access, "authorize", admin_access)
        if not callable(authorize) or not bool(authorize(assertion)):
            raise HTTPException(
                status_code=403,
                detail="Trusted admin access is required for Schwab authorization.",
            )

    @app.post("/api/auth/reauthorize")
    def begin_reauthorization(
        request: Request, response: Response
    ) -> dict[str, Any]:
        require_admin(request)
        response.headers["Cache-Control"] = "no-store"
        return companion.begin_schwab_reauthorization()

    @app.get("/api/auth/reauthorize/status")
    def poll_reauthorization(request: Request) -> dict[str, Any]:
        require_admin(request)
        return companion.poll_schwab_reauthorization()

    @app.post("/api/auth/resume-recording")
    def resume_recording_after_authorization(request: Request) -> dict[str, Any]:
        require_admin(request)
        try:
            return companion.resume_recording_after_authorization()
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    def _review_packet(
        engine: ReplayEngine,
        *,
        start_ms: int | None,
        end_ms: int | None,
        full_session: bool = False,
    ) -> dict[str, Any]:
        snapshot = engine.snapshot()
        replay_state = snapshot.get("replay") or {}
        symbol = str(replay_state.get("symbol") or "").upper()
        symbol_state = ((snapshot.get("session") or {}).get("symbols") or {}).get(symbol) or {}
        bars = []
        for bar in symbol_state.get("bars_10s") or []:
            bar_ms = int(bar.get("ts") or 0) * 1000
            if start_ms is not None and bar_ms < int(start_ms):
                continue
            if end_ms is not None and bar_ms > int(end_ms):
                continue
            item = dict(bar)
            item.setdefault("interval_seconds", 10)
            item.setdefault("source", "L1")
            bars.append(item)

        events = [
            event for event in engine._events
            if (start_ms is None or int(event["stream_ts_ms"]) >= int(start_ms))
            and (end_ms is None or int(event["stream_ts_ms"]) <= int(end_ms))
        ]
        gaps = []
        previous = None
        for event in events:
            ts = int(event["stream_ts_ms"])
            if previous is not None and ts - previous > 60_000:
                gaps.append(ts - previous)
            previous = ts

        return {
            "purpose": "momentum_full_session_review" if full_session else "momentum_review_window",
            "session_id": replay_state.get("session_id"),
            "symbol": symbol,
            "window": {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "future_data_included": False,
                "full_session": bool(full_session),
            },
            "bars_10s": bars,
            "vwap_points": [],
            "end_state": {
                "quote": symbol_state.get("quote") or {},
                "ae_snapshot": symbol_state.get("ae_snapshot") or {},
                "pattern_observations": symbol_state.get("pattern_observations") or [],
            },
            "replay": replay_state,
            "data_quality": {
                "evidence_tier": "L1",
                "significant_gap": {
                    "count": len(gaps),
                    "largest_ms": max(gaps) if gaps else 0,
                },
                "gap_repair": {"repaired_candles_consumed": 0},
                "volume": {"capped_total": 0, "discarded_total": 0},
                "receive_offset_ms": {},
            },
            "review_context": {
                "source": "deterministic_replay_compatibility",
                "events_in_window": len(events),
            },
        }

    @app.get("/api/review/recordings")
    def review_recordings() -> list[dict[str, Any]]:
        return replay.catalog.list_sessions()

    def _build_l1_quote_history(session_id: str, symbol: str) -> tuple[tuple[int, ...], tuple[dict[str, Any], ...]]:
        """Rebuild causal quote state from captured L1 deltas once per symbol.

        A bounded LRU prevents repeated full-day JSONL scans when WAMO requests
        multiple 120-second windows while also bounding historical cache size.
        No shared replay cursor or live runtime state is modified.
        """
        cache = LevelOneCache()
        frames: list[dict[str, Any]] = []
        for event in replay.catalog.load_events(session_id, symbol):
            ts = int(event["stream_ts_ms"])
            emitted = cache.process_messages({
                "service": "LEVELONE_EQUITIES",
                "timestamp": ts,
                "content": [event["raw"]],
            })
            for row in emitted:
                frames.append({
                    "timestamp_ms": ts,
                    "bid": row.get("bid"),
                    "ask": row.get("ask"),
                    "last": row.get("last"),
                    "bid_size": row.get("bid_size"),
                    "ask_size": row.get("ask_size"),
                    "last_size": row.get("last_size"),
                    "volume": row.get("volume"),
                })
        return tuple(frame["timestamp_ms"] for frame in frames), tuple(frames)

    _cached_complete_l1_quote_history = lru_cache(maxsize=4)(_build_l1_quote_history)

    @app.post("/api/review/l1-window")
    def review_l1_window(request: ReviewL1WindowRequest) -> dict[str, Any]:
        """Read-only captured Level 1 top-of-book snapshots in a bounded time window.

        This is a historical observation service, not an execution/fill endpoint.
        It reconstructs partial Schwab deltas in capture order; it neither
        interpolates unobserved quotes nor includes snapshots past end_ms.
        """
        if request.start_ms < 0 or request.end_ms < request.start_ms:
            raise HTTPException(status_code=400, detail="invalid review L1 time range")
        if request.end_ms - request.start_ms > 120_000:
            raise HTTPException(status_code=400, detail="L1 review window may not exceed 120 seconds")
        symbol = request.symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")
        try:
            manifest = replay.catalog.load_manifest(request.session_id)
            # Completed recordings are immutable; active captures must be
            # reconstructed afresh so the LRU never serves stale quotes.
            read_history = (
                _cached_complete_l1_quote_history
                if manifest.get("ended_at_et")
                else _build_l1_quote_history
            )
            timestamps, history = read_history(request.session_id, symbol)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        begin = bisect_left(timestamps, request.start_ms)
        end = bisect_right(timestamps, request.end_ms)
        return {
            "session_id": request.session_id,
            "symbol": symbol,
            "window": {
                "start_ms": request.start_ms,
                "end_ms": request.end_ms,
                "future_data_included": False,
            },
            "frames": list(history[begin:end]),
            "evidence_tier": "captured_L1_top_of_book",
        }

    @app.post("/api/review/window")
    def review_window(request: ReviewWindowRequest) -> dict[str, Any]:
        try:
            isolated = ReplayEngine(
                recordings_root=replay.catalog.root,
                max_bars_per_symbol=10_000,
            )
            state = isolated.load(request.session_id, request.symbol)
            total = int(state.get("total_events") or 0)
            if total == 0:
                return _review_packet(
                    isolated,
                    start_ms=request.start_ms,
                    end_ms=request.end_ms,
                )

            first_ms = int(isolated._events[0]["stream_ts_ms"])
            last_ms = int(isolated._events[-1]["stream_ts_ms"])
            requested_end = last_ms if request.end_ms is None else int(request.end_ms)
            requested_start = (
                requested_end - 20 * 60 * 1000
                if request.start_ms is None
                else int(request.start_ms)
            )
            if requested_start > requested_end:
                raise ValueError("start_ms must be <= end_ms")
            if requested_end - requested_start > 45 * 60 * 1000:
                raise ValueError("review window may not exceed 45 minutes")

            resolved_start = max(requested_start, first_ms)
            resolved_end = min(requested_end, last_ms)
            if resolved_start <= resolved_end:
                isolated.seek(isolated.cursor_for_timestamp(resolved_end))
            return _review_packet(
                isolated,
                start_ms=resolved_start,
                end_ms=resolved_end,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/review/session/{session_id}/{symbol}")
    def review_full_session(session_id: str, symbol: str) -> dict[str, Any]:
        try:
            isolated = ReplayEngine(
                recordings_root=replay.catalog.root,
                max_bars_per_symbol=10_000,
            )
            state = isolated.load(session_id, symbol)
            total = int(state.get("total_events") or 0)
            if total:
                isolated.step(total)
                start_ms = int(isolated._events[0]["stream_ts_ms"])
                end_ms = int(isolated._events[-1]["stream_ts_ms"])
            else:
                start_ms = None
                end_ms = None
            return _review_packet(
                isolated,
                start_ms=start_ms,
                end_ms=end_ms,
                full_session=True,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/replay/sessions")
    def replay_sessions() -> list[dict[str, Any]]:
        return replay.catalog.list_sessions()

    @app.get("/api/replay/state")
    def replay_state() -> dict[str, Any]:
        return replay.snapshot()

    @app.post("/api/replay/inspect")
    def replay_inspect(request: ReplayInspectRequest) -> dict[str, Any]:
        try:
            isolated = ReplayEngine(recordings_root=replay.catalog.root)
            isolated.load(request.session_id, request.symbol)
            if request.timestamp_ms is not None:
                isolated.seek(isolated.cursor_for_timestamp(request.timestamp_ms))
            elif request.cursor is not None:
                isolated.seek(request.cursor)
            return isolated.snapshot()
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/replay/load")
    def replay_load(request: ReplayLoadRequest) -> dict[str, Any]:
        try:
            replay.load(request.session_id, request.symbol)
            return replay.snapshot()
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/replay/play")
    def replay_play(request: ReplayPlayRequest) -> dict[str, Any]:
        try:
            replay.play(request.speed)
            return replay.snapshot()
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/replay/pause")
    def replay_pause() -> dict[str, Any]:
        replay.pause()
        return replay.snapshot()

    @app.post("/api/replay/step")
    def replay_step(request: ReplayStepRequest) -> dict[str, Any]:
        try:
            replay.step(request.count)
            return replay.snapshot()
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/replay/seek")
    def replay_seek(request: ReplaySeekRequest) -> dict[str, Any]:
        try:
            replay.seek(request.cursor)
            return replay.snapshot()
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
