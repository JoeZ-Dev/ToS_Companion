from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from momentum_companion.evaluation import (
    CorpusClassificationStore,
    DetectorAnnotationEvaluator,
)
from momentum_companion.evaluation.pattern_outcomes import build_pattern_outcomes
from momentum_companion.evaluation.pattern_overlaps import build_pattern_overlaps
from momentum_companion.evaluation.research_export import build_research_export
from momentum_companion.evaluation.pattern_parity import build_pattern_parity_report
from momentum_companion.evaluation.trade_simulation import build_trade_simulation
from momentum_companion.evaluation.trade_review import TradeReviewStore
from momentum_companion.replay import ReplayEngine
from momentum_companion.review import ReviewAnnotationStore, ReviewCorpus
from momentum_companion.runtime import CompanionRuntime
from momentum_companion.web.admin_access import AdminAccessVerifier


STATIC_DIR = Path(__file__).with_name("static")
class RecordingRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class RecordingSymbolRequest(BaseModel):
    symbol: str
    pre7_vwap: float | None = None
    pre7_volume: float | None = None


class Pre7SeedRequest(BaseModel):
    pre7_vwap: float
    pre7_volume: float


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


class ReviewVerificationRequest(BaseModel):
    session_id: str
    symbol: str
    trigger_ms: int
    lookback_ms: int = 10 * 60 * 1000


class ReviewL1WindowRequest(BaseModel):
    session_id: str
    symbol: str
    start_ms: int
    end_ms: int


class DetectorAuditRequest(BaseModel):
    session_id: str | None = None
    symbol: str | None = None
    default_lookback_ms: int = 5 * 60 * 1000
    post_trigger_ms: int = 2 * 60 * 1000


class CorpusClassificationRequest(BaseModel):
    classification: str
    note: str | None = None
    confirm_holdout_relabel: bool = False


class ReviewAnnotationRequest(BaseModel):
    session_id: str
    symbol: str
    setup_type: str
    trigger_ms: int
    valid_at_time: bool
    setup_start_ms: int | None = None
    outcome: str = "unknown"
    confidence: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    invalidation: str | None = None
    notes: str = ""
    review_pass: str = "discovery"
    source: str = "chatgpt"


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
    research_output_root: Path | None = None,
    admin_authorizer: Any | None = None,
) -> FastAPI:
    companion = runtime or CompanionRuntime()
    replay = replay_engine or ReplayEngine(
        recordings_root=Path.home() / ".tos_companion" / "recordings"
    )
    recordings_root = Path(
        getattr(
            replay.catalog,
            "root",
            Path.home() / ".tos_companion" / "recordings",
        )
    )
    review_corpus = ReviewCorpus(recordings_root)
    configured_research_root = research_output_root
    if configured_research_root is None:
        configured = os.environ.get("TOS_RESEARCH_OUTPUT_DIR", "").strip()
        configured_research_root = Path(configured) if configured else None
    trade_review = TradeReviewStore(configured_research_root, review_corpus)
    review_annotations = ReviewAnnotationStore(
        recordings_root.parent / "review_annotations"
    )
    corpus_store = CorpusClassificationStore(
        recordings_root.parent / "corpus_classifications.json"
    )
    detector_evaluator = DetectorAnnotationEvaluator(
        recordings_root=recordings_root,
        annotation_store=review_annotations,
        corpus_store=corpus_store,
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
    @app.get("/app-20260922-12.js")
    @app.get("/app-20260922-13.js")
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
    @app.get("/styles-20260922-6.css")
    @app.get("/styles-20260922-7.css")
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
    def begin_reauthorization(request: Request) -> dict[str, Any]:
        require_admin(request)
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
            return companion.add_recording_symbol(
                request.symbol,
                pre7_vwap=request.pre7_vwap,
                pre7_volume=request.pre7_volume,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/recording/symbol/{symbol}/pre7")
    def apply_recording_pre7_seed(
        symbol: str,
        request: Pre7SeedRequest,
    ) -> dict[str, Any]:
        try:
            return companion.apply_recording_pre7_seed(
                symbol,
                pre7_vwap=request.pre7_vwap,
                pre7_volume=request.pre7_volume,
            )
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

    @app.get("/api/replay/sessions")
    def replay_sessions() -> list[dict[str, Any]]:
        return replay.catalog.list_sessions()

    @app.get("/api/recordings/{session_id}/integrity")
    def recording_integrity(session_id: str) -> dict[str, Any]:
        try:
            return replay.catalog.integrity_report(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/evaluation/pattern-outcomes/{session_id}")
    def pattern_outcomes(
        session_id: str,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        try:
            return build_pattern_outcomes(
                replay.catalog.root,
                session_id,
                symbol=symbol,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/evaluation/pattern-overlaps/{session_id}")
    def pattern_overlaps(
        session_id: str,
        symbol: str | None = None,
        level_tolerance_pct: float = Query(default=1.0, ge=0),
    ) -> dict[str, Any]:
        try:
            return build_pattern_overlaps(
                replay.catalog.root,
                session_id,
                symbol=symbol,
                level_tolerance_pct=level_tolerance_pct,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/research/export")
    def research_export(
        session_id: str | None = None,
        symbol: str | None = None,
        pattern_type: str | None = None,
        corpus_classification: str | None = None,
        has_trigger: bool | None = None,
        start_ms: int | None = Query(default=None, ge=0),
        end_ms: int | None = Query(default=None, ge=0),
        include_outcomes: bool = False,
    ) -> dict[str, Any]:
        try:
            return build_research_export(
                replay.catalog.root,
                session_id=session_id,
                symbol=symbol,
                pattern_type=pattern_type,
                corpus_classification=corpus_classification,
                has_trigger=has_trigger,
                start_ms=start_ms,
                end_ms=end_ms,
                include_outcomes=include_outcomes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/trade-review/runs")
    def trade_review_runs() -> dict[str, Any]: return trade_review.runs()

    @app.get("/api/trade-review/opportunities")
    def trade_review_opportunities(run_id: str, trading_date: str | None = None,
        symbol: str | None = None, policy: str = "confirmed_detector_stop",
        outcome: str | None = None, eligibility: str | None = None) -> dict[str, Any]:
        try:
            return trade_review.opportunities(run_id=run_id, trading_date=trading_date,
                symbol=symbol, policy=policy, outcome=outcome, eligibility=eligibility)
        except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/trade-review/opportunities/{opportunity_id}")
    def trade_review_detail(opportunity_id: str, run_id: str) -> dict[str, Any]:
        try: return trade_review.detail(run_id, opportunity_id)
        except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/trade-review/paired")
    def trade_review_paired(run_id: str) -> dict[str, Any]:
        try: return trade_review.paired(run_id)
        except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/trade-review/chart/{opportunity_id}")
    def trade_review_chart(opportunity_id: str, run_id: str) -> dict[str, Any]:
        try: return trade_review.chart(run_id, opportunity_id)
        except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/trade-review/eligibility/{opportunity_id}")
    def trade_review_eligibility(opportunity_id: str, run_id: str) -> dict[str, Any]:
        try: return trade_review.eligibility(run_id, opportunity_id)
        except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/evaluation/pattern-parity/{session_id}")
    def pattern_parity(
        session_id: str,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        try:
            return build_pattern_parity_report(
                replay.catalog.root,
                session_id,
                symbol=symbol,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/evaluation/trade-simulation/{session_id}")
    def trade_simulation(
        session_id: str,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        try:
            return build_trade_simulation(
                replay.catalog.root,
                session_id,
                symbol=symbol,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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

    @app.get("/api/review/recordings")
    def review_recordings() -> list[dict[str, Any]]:
        recordings = review_corpus.list_recordings()
        for recording in recordings:
            recording["corpus"] = corpus_store.get(recording["session_id"])
        return recordings

    @app.get("/api/corpus/classifications")
    def corpus_classifications() -> list[dict[str, Any]]:
        session_ids = [
            item["session_id"] for item in replay.catalog.list_sessions()
        ]
        return corpus_store.list(session_ids)

    @app.get("/api/corpus/classifications/{session_id}")
    def corpus_classification(session_id: str) -> dict[str, Any]:
        try:
            replay.catalog.load_manifest(session_id)
            return corpus_store.get(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/corpus/classifications/{session_id}")
    def classify_corpus_session(
        session_id: str,
        request: CorpusClassificationRequest,
    ) -> dict[str, Any]:
        try:
            replay.catalog.load_manifest(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            return corpus_store.classify(
                session_id,
                request.classification,
                note=request.note,
                confirm_holdout_relabel=request.confirm_holdout_relabel,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/review/window")
    def review_window(request: ReviewWindowRequest) -> dict[str, Any]:
        try:
            return review_corpus.window(
                request.session_id,
                request.symbol,
                start_ms=request.start_ms,
                end_ms=request.end_ms,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/review/verify")
    def review_verify(request: ReviewVerificationRequest) -> dict[str, Any]:
        try:
            return review_corpus.verification_window(
                request.session_id,
                request.symbol,
                trigger_ms=request.trigger_ms,
                lookback_ms=request.lookback_ms,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/review/session/{session_id}/{symbol}")
    def review_full_session(session_id: str, symbol: str) -> dict[str, Any]:
        try:
            return review_corpus.full_session(session_id, symbol)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/review/l1-window")
    def review_l1_window(request: ReviewL1WindowRequest) -> dict[str, Any]:
        try:
            return review_corpus.l1_window(
                request.session_id,
                request.symbol,
                start_ms=request.start_ms,
                end_ms=request.end_ms,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/review/annotations")
    def review_annotation_list(
        session_id: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        return review_annotations.list(session_id=session_id, symbol=symbol)

    @app.post("/api/review/annotations")
    def review_annotation_add(request: ReviewAnnotationRequest) -> dict[str, Any]:
        try:
            return review_annotations.add(request.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/evaluation/detector-audit")
    def detector_audit(request: DetectorAuditRequest) -> dict[str, Any]:
        try:
            return detector_evaluator.audit(
                session_id=request.session_id,
                symbol=request.symbol,
                default_lookback_ms=request.default_lookback_ms,
                post_trigger_ms=request.post_trigger_ms,
            )
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
