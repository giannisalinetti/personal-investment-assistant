"""Discovery node — LLM correlated instrument suggestions with yfinance validation."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from src.config import load_watchlist
from src.llm import get_llm
from src.state import AgentState
from src.tools.yfinance_tool import validate_ticker

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 3
JSON_ARRAY_PATTERN = re.compile(r"\[.*\]", re.DOTALL)


def _discover_sync(watchlist_tickers: list[str], watchlist_names: list[str]) -> list[dict]:
    """Ask the LLM for correlated instruments (blocking)."""
    llm = get_llm(temperature=0.2)
    prompt = (
        "You are a market research assistant. Given this watchlist, suggest up to "
        f"{MAX_SUGGESTIONS} related stocks or ETFs the user might want to monitor.\n"
        f"Watchlist tickers: {', '.join(watchlist_tickers)}\n"
        f"Names: {', '.join(watchlist_names)}\n\n"
        "Return ONLY a JSON array. Each item must have keys: "
        'ticker, name, reason, confidence ("HIGH" or "MEDIUM").\n'
        "Do not suggest tickers already in the watchlist."
    )
    response = llm.invoke(prompt)
    content = str(response.content if hasattr(response, "content") else response)
    match = JSON_ARRAY_PATTERN.search(content)
    if not match:
        return []
    raw = json.loads(match.group())
    if not isinstance(raw, list):
        return []
    return raw


async def discovery_node(state: AgentState) -> dict:
    """Suggest correlated instruments and validate tickers via yfinance."""
    new_errors: list[str] = []
    suggestions: list[dict] = []
    entries = load_watchlist()
    watchlist_tickers = {entry.ticker.upper() for entry in entries}

    try:
        raw_suggestions = await asyncio.to_thread(
            _discover_sync,
            [entry.ticker for entry in entries],
            [entry.name for entry in entries],
        )
    except Exception as exc:
        message = f"Discovery LLM failed ({exc})"
        logger.warning(message)
        new_errors.append(message)
        return {"suggestions": suggestions, "discovered": suggestions, "errors": new_errors}

    for item in raw_suggestions[:MAX_SUGGESTIONS]:
        ticker = str(item.get("ticker", "")).upper().strip()
        confidence = str(item.get("confidence", "LOW")).upper()
        if not ticker or ticker in watchlist_tickers:
            continue
        if confidence not in {"HIGH", "MEDIUM"}:
            continue
        if not await validate_ticker(ticker):
            new_errors.append(f"Discovery: dropped invalid ticker {ticker}")
            continue

        suggestions.append(
            {
                "ticker": ticker,
                "name": str(item.get("name", ticker)),
                "reason": str(item.get("reason", "")),
                "type": "SUGGESTION",
                "confidence": confidence,
            }
        )

    logger.info("Discovery: %d validated suggestions", len(suggestions))
    return {
        "suggestions": suggestions,
        "discovered": suggestions,
        "errors": new_errors,
    }
