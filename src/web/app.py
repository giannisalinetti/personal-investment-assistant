"""FastAPI web application — `uv run pia-web`."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.advisor_history import clear_history, load_turns
from src.cli import command_parser
from src.config import load_watchlist, settings
from src.logging_config import configure_logging
from src.nodes.notifier import DISCLAIMER
from src.state_persistence import NEXT_RUNS
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


def create_app() -> FastAPI:
    app = FastAPI(title="Personal Investment Assistant", docs_url="/api/docs", redoc_url=None)
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

    def _page_context(request: Request, active: str) -> dict:
        token = settings.PIA_WEB_TOKEN.strip()
        token_query = f"?token={token}" if token else ""
        return {
            "request": request,
            "active": active,
            "disclaimer": DISCLAIMER,
            "model": settings.OLLAMA_MODEL,
            "auth_required": settings.web_auth_required,
            "token_query": token_query,
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

    @app.get("/about", response_class=HTMLResponse)
    async def about_page(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "about.html",
            {
                **_page_context(request, "about"),
                "watchlist_count": len(load_watchlist()),
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
            "Set PIA_WEB_TOKEN to require X-PIA-Token header or ?token= on API calls.\n\n"
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
