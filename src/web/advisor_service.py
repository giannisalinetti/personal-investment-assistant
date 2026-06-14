"""Advisor orchestration for the web UI (SSE status + shared advisor_respond)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from src.advisor_history import append_exchange, clear_history, load_turns
from src.advisor_scan import scan_status_message
from src.config import load_watchlist
from src.nodes.advisor import advisor_respond, resolve_advisor_targets
from src.state_persistence import load_state
from src.web.format import render_advisor_markdown

logger = logging.getLogger(__name__)

WEB_SESSION_ID = "web"


def _status_message(
    *,
    mode: str,
    question: str,
    targets: list,
    on_demand: dict | None,
    scan,
) -> str:
    if scan_message := scan_status_message(scan):
        return f"📊 {scan_message.capitalize()}…"
    if on_demand and on_demand.get("tickers"):
        tickers = ", ".join(on_demand["tickers"])
        return f"📊 On-demand analysis for {tickers}…"
    if targets:
        tickers = ", ".join(entry.ticker for entry in targets)
        return f"🧠 Fetching headlines for {tickers}…"
    if mode == "brief":
        return "🧠 Generating daily brief…"
    return "🧠 Thinking… this may take a few minutes."


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream_advisor(
    *,
    mode: str,
    question: str,
    lock: asyncio.Lock,
) -> AsyncIterator[str]:
    """Yield Server-Sent Events for Advisor progress and the final answer."""
    async with lock:
        yield _sse("status", {"message": "Starting…"})
        watchlist = load_watchlist()
        state = load_state()

        if state is None:
            yield _sse(
                "error",
                {
                    "message": (
                        "No Monitor run data found. Run `uv run pia-graph` before using the Advisor."
                    )
                },
            )
            return

        targets, on_demand, scan = await resolve_advisor_targets(
            question=question,
            watchlist=watchlist,
            mode=mode,
        )
        yield _sse(
            "status",
            {"message": _status_message(mode=mode, question=question, targets=targets, on_demand=on_demand, scan=scan)},
        )

        history = load_turns()
        try:
            answer = await advisor_respond(
                question=question,
                state=state,
                watchlist=watchlist,
                history=history,
                mode=mode,
                resolved=(targets, on_demand, scan),
            )
        except Exception as exc:
            logger.exception("Web advisor failed: %s", exc)
            yield _sse("error", {"message": f"Advisor request failed: {exc}"})
            return

        user_label = question if mode == "ask" and question else "/brief"
        append_exchange(
            user=user_label,
            assistant=answer,
            telegram_chat_id=WEB_SESSION_ID,
        )
        yield _sse(
            "done",
            {
                "answer": answer,
                "assistant_html": render_advisor_markdown(answer),
                "mode": mode,
            },
        )
