"""On-demand valuation fundamentals for Advisor mode (not used by Monitor)."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone

import yfinance as yf

from src.tools.yfinance_tool import YFINANCE_CACHE_DIR

logger = logging.getLogger(__name__)

yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))


def _normalize_ratio(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _fetch_fundamentals_sync(ticker: str) -> dict | None:
    """Fetch trailing P/E, forward P/E, and PEG from yfinance (blocking)."""
    stock = yf.Ticker(ticker)
    trailing_pe = forward_pe = peg_ratio = None

    try:
        fast = stock.fast_info
        trailing_pe = _normalize_ratio(getattr(fast, "trailing_pe", None))
        forward_pe = _normalize_ratio(getattr(fast, "forward_pe", None))
    except Exception:
        pass

    try:
        info = stock.info or {}
        trailing_pe = trailing_pe or _normalize_ratio(info.get("trailingPE"))
        forward_pe = forward_pe or _normalize_ratio(info.get("forwardPE"))
        peg_ratio = _normalize_ratio(info.get("pegRatio"))
    except Exception:
        logger.debug("Fundamentals info fetch failed for %s", ticker, exc_info=True)

    if trailing_pe is None and forward_pe is None and peg_ratio is None:
        return None

    return {
        "ticker": ticker,
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "peg_ratio": peg_ratio,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


async def fetch_fundamentals(ticker: str) -> dict | None:
    """Fetch valuation ratios asynchronously."""
    try:
        return await asyncio.to_thread(_fetch_fundamentals_sync, ticker)
    except Exception as exc:
        logger.warning("%s: fundamentals fetch failed: %s", ticker, exc)
        return None


async def fetch_fundamentals_batch(tickers: list[str]) -> tuple[dict[str, dict], list[str]]:
    """Fetch fundamentals for multiple tickers in parallel."""
    if not tickers:
        return {}, []

    unique = list(dict.fromkeys(tickers))
    results = await asyncio.gather(*[fetch_fundamentals(ticker) for ticker in unique])
    fundamentals: dict[str, dict] = {}
    errors: list[str] = []
    for ticker, payload in zip(unique, results, strict=True):
        if payload is None:
            errors.append(f"{ticker}: valuation metrics unavailable")
            continue
        fundamentals[ticker] = payload
    return fundamentals, errors
