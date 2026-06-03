"""Lightweight on-demand quote fetch for Advisor mode."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import yfinance as yf

from src.tools.yfinance_tool import YFINANCE_CACHE_DIR

logger = logging.getLogger(__name__)

yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))


def _fetch_quote_sync(ticker: str) -> dict | None:
    """Fetch latest price snapshot for one ticker (blocking)."""
    stock = yf.Ticker(ticker)
    try:
        fast = stock.fast_info
        last_price = getattr(fast, "last_price", None) or getattr(fast, "regular_market_price", None)
        previous_close = getattr(fast, "previous_close", None) or getattr(
            fast, "regular_market_previous_close", None
        )
        currency = getattr(fast, "currency", None)
        volume = getattr(fast, "last_volume", None) or getattr(fast, "regular_market_volume", None)
    except Exception:
        last_price = None
        previous_close = None
        currency = None
        volume = None

    if last_price is None:
        history = stock.history(period="5d", interval="1d", auto_adjust=True)
        if history.empty:
            return None
        last_price = float(history["Close"].iloc[-1])
        if len(history) >= 2:
            previous_close = float(history["Close"].iloc[-2])
        currency = currency or "USD"

    last_price = float(last_price)
    change_pct = None
    if previous_close not in (None, 0):
        change_pct = ((last_price - float(previous_close)) / float(previous_close)) * 100.0

    return {
        "ticker": ticker,
        "price": last_price,
        "change_pct": change_pct,
        "volume": int(volume) if volume is not None else None,
        "currency": currency or "USD",
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


async def fetch_quote(ticker: str) -> dict | None:
    """Fetch a live quote asynchronously."""
    try:
        return await asyncio.to_thread(_fetch_quote_sync, ticker)
    except Exception as exc:
        logger.warning("%s: quote fetch failed: %s", ticker, exc)
        return None


async def fetch_quotes(tickers: list[str]) -> tuple[dict[str, dict], list[str]]:
    """Fetch quotes for multiple tickers in parallel."""
    if not tickers:
        return {}, []

    unique = list(dict.fromkeys(tickers))
    results = await asyncio.gather(*[fetch_quote(ticker) for ticker in unique])
    quotes: dict[str, dict] = {}
    errors: list[str] = []
    for ticker, quote in zip(unique, results, strict=True):
        if quote is None:
            errors.append(f"{ticker}: quote unavailable")
            continue
        quotes[ticker] = quote
    return quotes, errors
