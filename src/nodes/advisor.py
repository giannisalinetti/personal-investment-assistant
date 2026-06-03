"""Advisor node — on-demand reasoning over persisted Monitor state."""

from __future__ import annotations

import asyncio
import json
import logging

from src.config import WatchlistEntry, settings
from src.llm import get_advisor_llm
from src.nodes.notifier import DISCLAIMER
from src.state_persistence import stale_state_warning

logger = logging.getLogger(__name__)

BRIEF_PROMPT = """Produce a daily brief for my watchlist covering:
1. Macro themes that matter for MY tickers this week (not generic market commentary)
2. Top 2–3 conflicts or alignments across the watchlist signals
3. What to watch before the next scheduled Monitor run

Use only facts from the context below. State assumptions explicitly. Be concise but substantive."""


def _format_watchlist_block(entries: list[WatchlistEntry]) -> str:
    lines = []
    for entry in entries:
        lines.append(
            f"- {entry.ticker}: {entry.name} "
            f"(RSI alerts {entry.rsi_oversold:g}/{entry.rsi_overbought:g})"
        )
    return "\n".join(lines)


def _format_state_block(state: dict) -> str:
    payload = {
        "last_run": state.get("last_run"),
        "run_type": state.get("run_type"),
        "skipped": state.get("skipped"),
        "watchlist_note": state.get("watchlist_note"),
        "signals": state.get("signals", []),
        "suggestions": state.get("suggestions", []),
        "errors": state.get("errors", []),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _build_prompt(
    *,
    question: str,
    state: dict,
    watchlist: list[WatchlistEntry],
    history: list[dict],
    mode: str,
) -> str:
    system = (
        "You are a personal investment advisor assistant. You help the user think through "
        "watchlist decisions — you never execute trades and have no portfolio access.\n"
        "Rules:\n"
        "- Use only data provided in the context; do not invent prices, headlines, or scores\n"
        "- Frame output as considerations and trade-offs, not direct buy/sell orders\n"
        "- State assumptions explicitly when data is incomplete\n"
        "- Reason step-by-step internally, then respond with clear prose only"
    )
    parts = [
        system,
        "",
        "=== Watchlist ===",
        _format_watchlist_block(watchlist),
        "",
        "=== Latest Monitor run ===",
        _format_state_block(state),
    ]
    if history:
        parts.extend(["", "=== Conversation history ==="])
        for turn in history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            parts.append(f"{role.upper()}: {content}")

    if mode == "brief":
        parts.extend(["", "=== Task ===", BRIEF_PROMPT])
    else:
        parts.extend(["", "=== User question ===", question])

    return "\n".join(parts)


def _invoke_advisor_sync(prompt: str) -> str:
    llm = get_advisor_llm()
    response = llm.invoke(prompt)
    return str(response.content if hasattr(response, "content") else response).strip()


def _ensure_disclaimer(text: str) -> str:
    if DISCLAIMER in text:
        return text
    return f"{text.rstrip()}\n\n{DISCLAIMER}"


async def advisor_respond(
    *,
    question: str,
    state: dict | None,
    watchlist: list[WatchlistEntry],
    history: list[dict] | None = None,
    mode: str = "ask",
) -> str:
    """Single entry point for Advisor LLM calls."""
    history = history or []
    warning = stale_state_warning(state)
    if state is None:
        return warning or "Monitor state unavailable."

    prompt = _build_prompt(
        question=question,
        state=state,
        watchlist=watchlist,
        history=history,
        mode=mode,
    )
    logger.info("Advisor invoke mode=%s prompt_chars=%d", mode, len(prompt))
    try:
        answer = await asyncio.to_thread(_invoke_advisor_sync, prompt)
    except Exception as exc:
        logger.exception("Advisor LLM failed: %s", exc)
        return f"Advisor request failed ({exc}). Check Ollama is running."

    if warning:
        answer = f"⚠️ {warning}\n\n{answer}"
    return _ensure_disclaimer(answer)
