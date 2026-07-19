"""FastAPI web application — `uv run pia-web`."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.advisor_history import clear_history, load_turns
from src.cli import command_parser
from src.config import AssetClass, load_watchlist, settings, watchlist_counts
from src.logging_config import configure_logging
from src.monitor_scheduler import (
    monitor_busy,
    monitor_status,
    start_monitor_scheduler,
    stop_monitor_scheduler,
    trigger_monitor_run,
)
from src.nodes.notifier import DISCLAIMER
from src.run_once import VALID_RUN_TYPES
from src.state_persistence import NEXT_RUNS
from src.investor_preferences import load_preferences, save_preferences
from src.watchlist_overlay import (
    clear_class_override,
    parse_entries_payload,
    set_class_override,
    settings_snapshot,
)
from src.web.advisor_service import stream_advisor
from src.web.auth import require_web_token
from src.web.history_view import exchange_by_id, exchanges_from_turns
from src.web.state_view import get_dashboard_view

configure_logging()
logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=WEB_DIR / "templates")


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)


class MonitorRunBody(BaseModel):
    run_type: str = "manual"


class WatchlistEntryBody(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    name: str = Field("", max_length=120)
    alerts: dict | None = None


class WatchlistPutBody(BaseModel):
    asset_class: AssetClass
    entries: list[WatchlistEntryBody] = Field(default_factory=list)


class WatchlistResetBody(BaseModel):
    asset_class: AssetClass | None = None


class PreferencesPutBody(BaseModel):
    horizon: str = "long"
    risk_tolerance: str = "moderate"
    base_currency: str = "EUR"
    prefer_ucits: bool = True
    notes: str = Field("", max_length=500)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    start_monitor_scheduler()
    try:
        yield
    finally:
        stop_monitor_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Personal Investment Assistant",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.advisor_lock = asyncio.Lock()

    static_dir = WEB_DIR / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.middleware("http")
    async def check_auth(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            require_web_token(request)
        return await call_next(request)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/state")
    async def api_state() -> JSONResponse:
        return JSONResponse(get_dashboard_view())

    @app.get("/api/monitor/status")
    async def api_monitor_status() -> JSONResponse:
        return JSONResponse(monitor_status())

    @app.post("/api/monitor/run")
    async def api_monitor_run(body: MonitorRunBody | None = None) -> JSONResponse:
        run_type = (body.run_type if body else "manual").strip().lower() or "manual"
        if run_type not in VALID_RUN_TYPES:
            raise HTTPException(status_code=400, detail=f"run_type must be one of {VALID_RUN_TYPES}")
        if monitor_busy():
            raise HTTPException(status_code=409, detail="Monitor run already in progress")
        result = await trigger_monitor_run(run_type=run_type, wait=True)
        if result.get("status") == "conflict":
            raise HTTPException(status_code=409, detail=result.get("message", "busy"))
        status_code = 200 if result.get("status") == "ok" else 500
        return JSONResponse(result, status_code=status_code)

    @app.get("/api/advisor/exchanges")
    async def api_exchanges() -> JSONResponse:
        turns = load_turns()
        exchanges = exchanges_from_turns(turns)
        items = [{"id": item["id"], "preview": item["preview"]} for item in reversed(exchanges)]
        return JSONResponse({"exchanges": items})

    @app.get("/api/advisor/exchanges/{exchange_id}")
    async def api_exchange(exchange_id: int) -> JSONResponse:
        exchange = exchange_by_id(load_turns(), exchange_id)
        if exchange is None:
            raise HTTPException(status_code=404, detail="Exchange not found")
        return JSONResponse(exchange)

    @app.get("/api/advisor/history")
    async def api_history() -> JSONResponse:
        turns = load_turns()
        return JSONResponse({"turns": turns[-20:]})

    @app.post("/api/advisor/clear")
    async def api_clear() -> JSONResponse:
        clear_history(telegram_chat_id="web")
        return JSONResponse({"cleared": True})

    @app.get("/api/advisor/stream")
    async def api_advisor_stream(
        request: Request,
        mode: str = "ask",
        question: str = "",
    ) -> StreamingResponse:
        require_web_token(request)
        normalized = mode.strip().lower()
        if normalized not in {"ask", "brief"}:
            raise HTTPException(status_code=400, detail="mode must be ask or brief")
        if normalized == "ask" and not question.strip():
            raise HTTPException(status_code=400, detail="question is required for ask mode")

        return StreamingResponse(
            stream_advisor(
                mode=normalized,
                question=question.strip(),
                lock=request.app.state.advisor_lock,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/advisor/ask")
    async def api_advisor_ask(body: AskBody, request: Request) -> StreamingResponse:
        require_web_token(request)
        return StreamingResponse(
            stream_advisor(
                mode="ask",
                question=body.question.strip(),
                lock=request.app.state.advisor_lock,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/advisor/brief")
    async def api_advisor_brief(request: Request) -> StreamingResponse:
        require_web_token(request)
        return StreamingResponse(
            stream_advisor(
                mode="brief",
                question="",
                lock=request.app.state.advisor_lock,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/settings/watchlists")
    async def api_settings_watchlists_get() -> JSONResponse:
        return JSONResponse(settings_snapshot())

    @app.put("/api/settings/watchlists")
    async def api_settings_watchlists_put(body: WatchlistPutBody) -> JSONResponse:
        entries = parse_entries_payload(
            [item.model_dump() for item in body.entries],
            body.asset_class,
        )
        set_class_override(body.asset_class, entries)
        return JSONResponse(settings_snapshot())

    @app.post("/api/settings/watchlists/reset")
    async def api_settings_watchlists_reset(
        body: WatchlistResetBody = Body(default_factory=WatchlistResetBody),
    ) -> JSONResponse:
        # Body() is required: optional `Model | None = None` skips JSON and always
        # passed None, which incorrectly cleared every class.
        clear_class_override(body.asset_class)
        return JSONResponse(settings_snapshot())

    @app.get("/api/settings/preferences")
    async def api_settings_preferences_get() -> JSONResponse:
        return JSONResponse(load_preferences().model_dump())

    @app.put("/api/settings/preferences")
    async def api_settings_preferences_put(body: PreferencesPutBody) -> JSONResponse:
        from pydantic import ValidationError

        try:
            saved = save_preferences(body.model_dump())
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.errors()) from exc
        return JSONResponse(saved.model_dump())

    def _page_context(request: Request, active: str) -> dict:
        token = settings.PIA_WEB_TOKEN.strip()
        token_query = f"?token={token}" if token else ""
        monitor_p = settings.resolved_monitor_provider()
        advisor_p = settings.resolved_advisor_provider()
        if monitor_p == advisor_p == "ollama":
            model_label = f"ollama/{settings.OLLAMA_MODEL}"
        elif monitor_p == advisor_p:
            mid = (
                settings.ANTHROPIC_MODEL
                if monitor_p == "anthropic"
                else settings.OPENAI_MODEL
                if monitor_p in {"openai", "openai-compatible", "vllm"}
                else settings.OLLAMA_MODEL
            )
            model_label = f"{monitor_p}/{mid}"
        else:
            model_label = f"monitor={monitor_p}, advisor={advisor_p}"
        return {
            "request": request,
            "active": active,
            "disclaimer": DISCLAIMER,
            "model": model_label,
            "auth_required": settings.web_auth_required,
            "token_query": token_query,
            "monitor_scheduler": settings.PIA_MONITOR_SCHEDULER,
            "next_runs": NEXT_RUNS,
            "timezone": settings.TIMEZONE,
        }

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_page(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            {**_page_context(request, "dashboard"), "dashboard": get_dashboard_view()},
        )

    @app.get("/advisor", response_class=HTMLResponse)
    async def advisor_page(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "advisor.html",
            _page_context(request, "advisor"),
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "settings.html",
            _page_context(request, "settings"),
        )

    @app.get("/about", response_class=HTMLResponse)
    async def about_page(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "about.html",
            {
                **_page_context(request, "about"),
                "watchlist_count": len(load_watchlist()),
                "watchlist_counts": watchlist_counts(),
                "next_runs": NEXT_RUNS,
                "timezone": settings.TIMEZONE,
            },
        )

    return app


def _parse_args() -> None:
    parser = command_parser(
        "pia-web",
        "Local web UI — Monitor dashboard and Advisor chat.",
        epilog=(
            "Serves on PIA_WEB_HOST:PIA_WEB_PORT (default 127.0.0.1:8765).\n"
            "Set PIA_WEB_TOKEN to require X-PIA-Token header or ?token= on API calls.\n"
            "PIA_MONITOR_SCHEDULER=true (default) runs Monitor at 08:00/13:00/17:30.\n\n"
            "Example:\n"
            "  uv run pia-web\n"
            "  open http://127.0.0.1:8765"
        ),
    )
    parser.parse_args()


def main() -> None:
    _parse_args()
    app = create_app()
    logger.info(
        "Starting PIA web UI on http://%s:%s",
        settings.PIA_WEB_HOST,
        settings.PIA_WEB_PORT,
    )
    uvicorn.run(
        app,
        host=settings.PIA_WEB_HOST,
        port=settings.PIA_WEB_PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
